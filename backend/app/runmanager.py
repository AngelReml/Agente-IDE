"""
Durable, reconnectable runs (Fase 2, in-process foundation).

v4.0 tied a run to the SSE request: if the client disconnected, the run died.
Here a run executes in a background task and buffers its events, so:
  • the client can disconnect and reconnect without losing the run, and
  • a late subscriber gets the full backlog then the live tail.

This is the local foundation; the production path swaps the in-process registry
for a Redis-backed queue + worker pool (same interface). The agent driver is
injectable so the manager is unit-testable without the LLM stack.
"""
import asyncio
import logging
import uuid
from typing import AsyncGenerator, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_END = {"type": "_end"}

# An agent is an async generator: agent(task, session_id) -> events
AgentFactory = Callable[[str, str], "AsyncGenerator[dict, None]"]


class _Run:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.done = False
        self.task: Optional[asyncio.Task] = None

    def publish(self, ev: dict) -> None:
        self.events.append(ev)
        for q in self.subscribers:
            q.put_nowait(ev)


class RunManager:
    def __init__(self, agent_factory: AgentFactory | None = None):
        self._agent = agent_factory
        self._runs: dict[str, _Run] = {}

    async def start(self, task: str, session_id: str = "default",
                    agent: AgentFactory | None = None) -> str:
        agent_fn = agent or self._agent
        if agent_fn is None:
            raise RuntimeError("RunManager sin agente configurado")
        run_id = uuid.uuid4().hex[:12]
        run = _Run(run_id)
        self._runs[run_id] = run

        async def driver() -> None:
            try:
                async for ev in agent_fn(task, session_id):
                    run.publish(ev)
            except asyncio.CancelledError:
                run.publish({"type": "info", "content": "⏹ Run cancelado"})
            except Exception as e:  # pragma: no cover - defensive
                logger.exception("run %s failed", run_id)
                run.publish({"type": "error", "content": str(e)[:300]})
            finally:
                run.done = True
                run.publish(_END)

        run.task = asyncio.create_task(driver())
        return run_id

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict, None]:
        run = self._runs.get(run_id)
        if run is None:
            return
        # Replay the backlog so a reconnecting client catches up.
        for ev in list(run.events):
            if ev is _END:
                return
            yield ev
        if run.done:
            return
        q: asyncio.Queue = asyncio.Queue()
        run.subscribers.append(q)
        try:
            while True:
                ev = await q.get()
                if ev is _END:
                    return
                yield ev
        finally:
            if q in run.subscribers:
                run.subscribers.remove(q)

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.task and not run.task.done():
            run.task.cancel()
            return True
        return False

    def exists(self, run_id: str) -> bool:
        return run_id in self._runs

    def active(self) -> list[str]:
        return [rid for rid, r in self._runs.items() if not r.done]
