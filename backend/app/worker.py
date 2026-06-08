"""
Arq worker entrypoint (Fase 2 — scale path).

Run with:  arq app.worker.WorkerSettings   (needs `arq` + REDIS_URL)

Executes swarm runs out-of-process so the API stays responsive and runs survive
an API restart. Locally you don't need this — the in-process queue handles runs.
"""
import os


async def run_swarm_job(ctx, task: str, session_id: str = "default") -> dict:  # pragma: no cover
    """Worker task: drive a swarm run to completion, persisting events."""
    from . import graph, store, runtime
    rc = runtime.new_run(task, session_id)
    store.start_run(rc.run_id, session_id, task)
    last = {}
    async for ev in graph.run_swarm_stream(task, session_id):
        store.record_event(rc.run_id, ev.get("type", ""), ev.get("content", ""), ev.get("tool"))
        last = ev
    store.finish_run(rc.run_id, "done", rc.provider, rc.model, rc.cost.stats())
    return {"run_id": rc.run_id, "final": last}


class WorkerSettings:  # pragma: no cover - requires arq runtime
    functions = [run_swarm_job]

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings
        return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
