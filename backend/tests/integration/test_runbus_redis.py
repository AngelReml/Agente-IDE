"""Integration smoke for the out-of-process path (Fase 6, paso 4) against a REAL
Redis — the seams that the unit tests can only fake.

Covers:
  1. RedisBus  — XADD/XREAD replay + live tail + _END termination.
  2. worker.run_swarm_job → RedisBus → tail, end to end (fake agent, no LLM/Docker).
  3. arq enqueue → burst worker → job ran (the queue round-trip).

Runs ONLY when a real Redis is reachable via SWARM_TEST_REDIS_URL; otherwise the
whole module is skipped, so the default suite / CI are never affected. Bring Redis
up with `make integration` (or point the env var at any Redis).

    SWARM_TEST_REDIS_URL=redis://:pass@127.0.0.1:6379/0 python -m pytest tests/integration -v
"""
import asyncio
import os
import uuid

import pytest

# Skip cleanly if the platform deps or a live Redis aren't present.
pytest.importorskip("redis", reason="redis no instalado (requirements-platform.txt)")
pytest.importorskip("arq", reason="arq no instalado (requirements-platform.txt)")

REDIS_URL = os.getenv("SWARM_TEST_REDIS_URL", "")
if not REDIS_URL:
    pytest.skip("SWARM_TEST_REDIS_URL no definido — integración Redis omitida",
                allow_module_level=True)

import redis as _redis_sync  # noqa: E402

try:
    _probe = _redis_sync.from_url(REDIS_URL, socket_connect_timeout=2)
    _probe.ping()
    _probe.close()
except Exception as e:  # noqa: BLE001
    pytest.skip(f"Redis no accesible en {REDIS_URL}: {e}", allow_module_level=True)

from app import runbus, worker  # noqa: E402


def _rid() -> str:
    return "it-" + uuid.uuid4().hex[:10]


async def _drain(bus, run_id, timeout=10):
    out = []

    async def consume():
        async for ev in bus.subscribe(run_id):
            out.append(ev)

    await asyncio.wait_for(consume(), timeout=timeout)
    return out


# ── 1. RedisBus transport ────────────────────────────────────────────────────────

def test_redisbus_replay_then_end():
    async def scenario():
        bus = runbus.RedisBus(REDIS_URL)
        rid = _rid()
        try:
            for i in range(3):
                await bus.publish(rid, {"type": "token", "content": str(i)})
            await bus.publish(rid, runbus.END)
            # Subscribing after the fact replays from offset 0 and stops at _END.
            return await _drain(bus, rid)
        finally:
            r = await bus._client()
            await r.delete(bus._key(rid))

    out = asyncio.run(scenario())
    assert [e["content"] for e in out] == ["0", "1", "2"]


def test_redisbus_live_tail():
    async def scenario():
        bus = runbus.RedisBus(REDIS_URL)
        rid = _rid()
        out = []

        async def consume():
            async for ev in bus.subscribe(rid):
                out.append(ev)

        try:
            t = asyncio.create_task(consume())
            await asyncio.sleep(0.2)  # subscriber blocks on XREAD before any event
            await bus.publish(rid, {"type": "info", "content": "a"})
            await bus.publish(rid, {"type": "info", "content": "b"})
            await bus.publish(rid, runbus.END)
            await asyncio.wait_for(t, timeout=10)
            return out
        finally:
            r = await bus._client()
            await r.delete(bus._key(rid))

    out = asyncio.run(scenario())
    assert [e["content"] for e in out] == ["a", "b"]


# ── 2. worker.run_swarm_job → RedisBus → tail (no LLM/Docker) ─────────────────────

class _FakeStore:
    def __init__(self):
        self.events = []
        self.finished = None

    def start_run(self, *a):
        pass

    def record_event(self, run_id, etype, content="", tool=None):
        self.events.append((etype, content))

    def finish_run(self, run_id, status, provider, model, cost):
        self.finished = status


def test_worker_job_streams_over_real_redis():
    bus = runbus.RedisBus(REDIS_URL)
    store = _FakeStore()
    rid = _rid()

    async def fake_agent(task, session_id):
        yield {"type": "model", "content": "m", "provider": "p", "model": "x"}
        yield {"type": "token", "content": "hi"}
        yield {"type": "done", "content": "ok"}

    async def scenario():
        try:
            res = await worker.run_swarm_job(
                None, "t", "s", run_id=rid, agent=fake_agent, bus=bus, store_mod=store)
            tailed = await _drain(bus, rid)
            return res, tailed
        finally:
            r = await bus._client()
            await r.delete(bus._key(rid))

    res, tailed = asyncio.run(scenario())
    assert res == {"run_id": rid, "status": "done"}
    assert [e["type"] for e in tailed] == ["model", "token", "done"]
    assert store.finished == "done" and ("token", "hi") not in store.events


# ── 3. arq enqueue → burst worker → job executed ─────────────────────────────────

async def _marker_job(ctx, key):
    import redis.asyncio as ar
    r = ar.from_url(REDIS_URL)
    await r.set(key, "done")
    await r.aclose()


def test_arq_enqueue_and_burst_consume():
    async def scenario():
        from arq import create_pool
        from arq.connections import RedisSettings
        from arq.worker import Worker

        settings = RedisSettings.from_dsn(REDIS_URL)
        key = _rid()
        pool = await create_pool(settings)
        await pool.enqueue_job("_marker_job", key)
        # Burst worker drains the queue once and exits.
        w = Worker(functions=[_marker_job], redis_settings=settings,
                   burst=True, poll_delay=0.1)
        await w.async_run()

        import redis.asyncio as ar
        r = ar.from_url(REDIS_URL)
        val = await r.get(key)
        await r.delete(key)
        await r.aclose()
        return val

    val = asyncio.run(scenario())
    assert val in (b"done", "done")
