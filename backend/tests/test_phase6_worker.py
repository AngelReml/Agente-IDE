"""Phase 6 step 4 (architecture plan): out-of-process execution.

The API enqueues runs to the Arq worker (the only process that touches Docker) and
tails events from the run bus. These tests exercise the in-process bus, the
RunManager remote-routing decision, and the worker job — all with fakes, so no
Redis/Docker is needed. The local (no-REDIS_URL) path is covered by the existing
in-process RunManager tests and stays byte-for-byte unchanged.
"""
import asyncio

from app import runbus, worker
from app.runmanager import RunManager


# ── InProcessBus: ordered log with replay + live tail ────────────────────────────

def test_bus_replays_backlog_then_ends():
    async def scenario():
        bus = runbus.InProcessBus()
        for i in range(3):
            await bus.publish("r1", {"type": "token", "content": str(i)})
        await bus.publish("r1", runbus.END)
        # Subscribing AFTER everything was published still replays the full backlog.
        return [ev async for ev in bus.subscribe("r1")]

    out = asyncio.run(scenario())
    assert [e["content"] for e in out] == ["0", "1", "2"]  # _END terminates, not yielded


def test_bus_live_tail():
    async def scenario():
        bus = runbus.InProcessBus()
        out = []

        async def consumer():
            async for ev in bus.subscribe("r2"):
                out.append(ev)

        t = asyncio.create_task(consumer())
        await asyncio.sleep(0)  # let the consumer subscribe and block on the tail
        await bus.publish("r2", {"type": "info", "content": "a"})
        await bus.publish("r2", {"type": "info", "content": "b"})
        await bus.publish("r2", runbus.END)
        await asyncio.wait_for(t, timeout=2)
        return out

    out = asyncio.run(scenario())
    assert [e["content"] for e in out] == ["a", "b"]


def test_bus_multiple_subscribers_each_get_all():
    async def scenario():
        bus = runbus.InProcessBus()
        await bus.publish("r3", {"type": "info", "content": "x"})
        await bus.publish("r3", runbus.END)
        a = [ev async for ev in bus.subscribe("r3")]
        b = [ev async for ev in bus.subscribe("r3")]
        return a, b

    a, b = asyncio.run(scenario())
    assert len(a) == 1 and len(b) == 1 and a[0]["content"] == "x"


# ── RunManager: remote routing (enqueue instead of in-process driver) ────────────

class _FakeRedisQueue:
    name = "redis"

    def __init__(self):
        self.enqueued = []

    async def enqueue_named(self, func_name, *args):
        self.enqueued.append((func_name, args))
        return "job-1"


def test_runmanager_enqueues_and_tails_when_remote(monkeypatch):
    fake_q = _FakeRedisQueue()
    bus = runbus.InProcessBus()
    # Force "remote" mode and a shared bus, without REDIS_URL or a real worker.
    monkeypatch.setattr(RunManager, "_remote_queue", lambda self: fake_q)
    monkeypatch.setattr(runbus, "get_bus", lambda: bus)

    async def scenario():
        mgr = RunManager(agent_factory=None, persist=False)  # no in-process agent needed
        run_id = await mgr.start("hazlo", "sess", mode="swarm")
        # The API enqueued the job for the worker; it did NOT run anything in-process.
        assert fake_q.enqueued == [("run_swarm_job", ("hazlo", "sess", run_id, "swarm"))]
        # Simulate the worker publishing the run's events to the shared bus.
        await bus.publish(run_id, {"type": "info", "content": "trabajando"})
        await bus.publish(run_id, {"type": "done", "content": "listo"})
        await bus.publish(run_id, runbus.END)
        return [ev async for ev in mgr.subscribe(run_id)]

    events = asyncio.run(scenario())
    types = [e["type"] for e in events]
    assert "info" in types and "done" in types and "_end" not in types


# ── Worker job: drives the agent, publishes to the bus, persists ─────────────────

class _FakeStore:
    def __init__(self):
        self.started = None
        self.events = []
        self.finished = None

    def start_run(self, run_id, session_id, task):
        self.started = (run_id, session_id, task)

    def record_event(self, run_id, etype, content="", tool=None):
        self.events.append((etype, content))

    def finish_run(self, run_id, status, provider, model, cost):
        self.finished = (run_id, status, provider, model)


def test_worker_job_publishes_and_persists():
    bus = runbus.InProcessBus()
    store = _FakeStore()

    async def fake_agent(task, session_id):
        yield {"type": "model", "content": "x", "provider": "openai", "model": "gpt"}
        yield {"type": "token", "content": "hel"}      # volatile → streamed, not persisted
        yield {"type": "done", "content": "ok"}

    async def scenario():
        res = await worker.run_swarm_job(
            None, "t", "s", run_id="rid", mode="single",
            agent=fake_agent, bus=bus, store_mod=store)
        tailed = [ev async for ev in bus.subscribe("rid")]
        return res, tailed

    res, tailed = asyncio.run(scenario())
    assert res == {"run_id": "rid", "status": "done"}
    # Bus carried every event (incl. the volatile token); _END closed the stream.
    assert [e["type"] for e in tailed] == ["model", "token", "done"]
    # Store: start + finish recorded; token NOT persisted; provider/model captured.
    assert store.started == ("rid", "s", "t")
    assert ("token", "hel") not in store.events
    assert ("model", "x") in store.events and ("done", "ok") in store.events
    assert store.finished == ("rid", "done", "openai", "gpt")


def test_worker_job_reports_agent_failure():
    bus = runbus.InProcessBus()
    store = _FakeStore()

    async def boom_agent(task, session_id):
        yield {"type": "info", "content": "empezando"}
        raise RuntimeError("explotó")

    async def scenario():
        res = await worker.run_swarm_job(
            None, "t", "s", run_id="rid", agent=boom_agent, bus=bus, store_mod=store)
        tailed = [ev async for ev in bus.subscribe("rid")]
        return res, tailed

    res, tailed = asyncio.run(scenario())
    assert res["status"] == "error"
    assert any(e["type"] == "error" and "explotó" in e["content"] for e in tailed)
    assert store.finished[1] == "error"
