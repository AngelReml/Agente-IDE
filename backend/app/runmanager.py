"""
Durable, reconnectable runs (Fase 2, in-process foundation).

v4.0 tied a run to the SSE request: if the client disconnected, the run died.
Here a run executes in a background task and buffers its events, so:
  • the client can disconnect and reconnect without losing the run, and
  • a late subscriber gets the full backlog then the live tail.

Hardening (post-audit):
  • the per-run event buffer is bounded (deque maxlen) and finished runs are
    evicted with an LRU cap, so the process no longer grows without bound, and
  • runs are persisted to the store (start/events/finish), so they survive a
    restart and `/api/runs` reflects in-process runs (it used to be empty).

This is the local foundation; the production path swaps the in-process registry
for a Redis-backed queue + worker pool (same interface). The agent driver is
injectable so the manager is unit-testable without the LLM stack.
"""
import asyncio
import logging
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncGenerator, Callable

from . import config

logger = logging.getLogger(__name__)

_END = {"type": "_end"}

# An agent is an async generator: agent(task, session_id) -> events
AgentFactory = Callable[[str, str], "AsyncGenerator[dict, None]"]

# Streaming chunk types we do NOT persist per-event (too high-volume / low-value).
_VOLATILE_EVENT_TYPES = frozenset({"token", "_end"})


class _Run:
    def __init__(self, run_id: str, session_id: str = "default", task: str = "", remote: bool = False):
        self.run_id = run_id
        self.session_id = session_id
        self.task = task
        # Remote runs execute in the Arq worker; their events arrive via the run bus,
        # not the in-process driver, so this _Run is just a routing/registry handle.
        self.remote = remote
        # Bounded buffer: a reconnecting client replays the recent tail, not an
        # unbounded history that would eventually OOM the process.
        self.events: deque[dict] = deque(maxlen=config.RUN_EVENT_BUFFER)
        self.subscribers: list[asyncio.Queue] = []
        self.done = False
        self.status = "running"
        self.provider: str | None = None
        self.model: str | None = None
        self.started_at = time.time()
        self.task_handle: asyncio.Task | None = None

    def publish(self, ev: dict) -> None:
        self.events.append(ev)
        for q in self.subscribers:
            q.put_nowait(ev)


class RunManager:
    def __init__(self, agent_factory: AgentFactory | None = None, persist: bool = True):
        self._agent = agent_factory
        self._runs: OrderedDict[str, _Run] = OrderedDict()
        self._persist = persist

    def _evict(self) -> None:
        """Keep memory bounded: drop the oldest FINISHED runs beyond the cap.
        Active runs are never evicted."""
        while len(self._runs) > config.MAX_RETAINED_RUNS:
            for rid, r in self._runs.items():
                if r.done:
                    self._runs.pop(rid, None)
                    break
            else:
                break  # nothing finished to evict yet

    def _store(self, phase: str, run: "_Run", ev: dict | None = None) -> None:
        """Best-effort persistence. Never raises into the run."""
        if not self._persist:
            return
        try:
            from . import cost_tracker, store
            if phase == "start":
                store.start_run(run.run_id, run.session_id, run.task)
            elif phase == "event" and ev is not None and ev.get("type") not in _VOLATILE_EVENT_TYPES:
                store.record_event(run.run_id, ev.get("type", ""), ev.get("content", ""), ev.get("tool"))
            elif phase == "finish":
                store.finish_run(run.run_id, run.status, run.provider, run.model,
                                 cost_tracker.run_stats())
        except Exception:  # pragma: no cover - persistence must never break a run
            logger.debug("run persistence (%s) failed for %s", phase, run.run_id, exc_info=True)

    def _remote_queue(self):
        """The Redis queue if execution should happen out-of-process, else None.
        When None (no REDIS_URL / arq), runs execute in-process exactly as before."""
        try:
            from . import queue
            q = queue.get_queue()
            return q if getattr(q, "name", "") == "redis" else None
        except Exception:  # pragma: no cover - defensive
            return None

    async def start(self, task: str, session_id: str = "default",
                    agent: AgentFactory | None = None, mode: str = "single") -> str:
        run_id = uuid.uuid4().hex[:12]

        remote_q = self._remote_queue()
        if remote_q is not None:
            # Out-of-process: the API only enqueues; the worker (the sole process with
            # Docker/proxy access) runs the swarm and publishes events to the run bus.
            self._runs[run_id] = _Run(run_id, session_id, task, remote=True)
            self._evict()
            await remote_q.enqueue_named("run_swarm_job", task, session_id, run_id, mode)
            return run_id

        agent_fn = agent or self._agent
        if agent_fn is None:
            raise RuntimeError("RunManager sin agente configurado")
        run = _Run(run_id, session_id, task)
        self._runs[run_id] = run
        self._evict()
        self._store("start", run)

        async def driver() -> None:
            try:
                async for ev in agent_fn(task, session_id):
                    run.publish(ev)
                    if isinstance(ev, dict):
                        if ev.get("provider"):
                            run.provider = ev.get("provider")
                        if ev.get("model"):
                            run.model = ev.get("model")
                    self._store("event", run, ev)
                run.status = "done"
            except asyncio.CancelledError:
                run.status = "cancelled"
                run.publish({"type": "info", "content": "⏹ Run cancelado"})
            except Exception as e:  # pragma: no cover - defensive
                run.status = "error"
                logger.exception("run %s failed", run_id)
                run.publish({"type": "error", "content": str(e)[:300]})
            finally:
                run.done = True
                run.publish(_END)
                self._store("finish", run)

        run.task_handle = asyncio.create_task(driver())
        return run_id

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict, None]:
        run = self._runs.get(run_id)
        if run is None:
            return
        if run.remote:
            # Events live in the run bus (worker → Redis Stream); replay + tail there.
            from . import runbus
            async for ev in runbus.get_bus().subscribe(run_id):
                yield ev
            return
        # Register the live queue BEFORE snapshotting the backlog, so an event
        # published in between is captured by the queue rather than lost. We then
        # de-duplicate by skipping queued events already present in the backlog.
        q: asyncio.Queue = asyncio.Queue()
        if not run.done:
            run.subscribers.append(q)
        # Snapshot the backlog AFTER registering the queue (no await in between, so
        # it's atomic vs. the driver). Any event that lands in both the backlog and
        # the queue is de-duplicated by object identity, so the subscriber sees each
        # event exactly once with no lost-event race.
        backlog = list(run.events)
        backlog_ids = {id(ev) for ev in backlog}
        try:
            for ev in backlog:
                if ev is _END:
                    return
                yield ev
            if run.done:
                return
            while True:
                ev = await q.get()
                if id(ev) in backlog_ids:
                    continue  # already replayed from the backlog snapshot
                if ev is _END:
                    return
                yield ev
        finally:
            if q in run.subscribers:
                run.subscribers.remove(q)

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.remote:
            return False  # remote cancellation (worker abort) not yet supported
        if run and run.task_handle and not run.task_handle.done():
            run.task_handle.cancel()
            return True
        return False

    def exists(self, run_id: str) -> bool:
        return run_id in self._runs

    def active(self) -> list[str]:
        return [rid for rid, r in self._runs.items() if not r.done]
