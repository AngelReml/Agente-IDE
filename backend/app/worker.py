"""
Arq worker entrypoint (Fase 2 — scale path).

Run with:  arq app.worker.WorkerSettings   (needs `arq` + REDIS_URL)

Executes swarm runs out-of-process so the API stays responsive and runs survive
an API restart. Locally you don't need this — the in-process queue handles runs.
"""
import os

# High-volume / low-value events we stream but don't persist per-event (matches
# RunManager): the live tail still carries them via the bus.
_VOLATILE_EVENT_TYPES = frozenset({"token", "_end"})


async def run_swarm_job(ctx, task: str, session_id: str = "default",
                        run_id: str | None = None, mode: str = "single",
                        agent=None, bus=None, store_mod=None) -> dict:
    """Worker task: drive a run to completion out-of-process, publishing each event
    to the run bus (so the API can tail it) and persisting it (so it survives a
    restart). `agent`/`bus`/`store_mod` are injectable for unit tests."""
    import uuid as _uuid

    from . import cost_tracker, graph, orchestrator, runbus, store
    bus = bus or runbus.get_bus()
    store_mod = store_mod or store
    if agent is None:
        agent = orchestrator.run_orchestrated if mode == "swarm" else graph.run_swarm_stream
    run_id = run_id or _uuid.uuid4().hex[:12]

    store_mod.start_run(run_id, session_id, task)
    provider = model = None
    status = "error"
    try:
        async for ev in agent(task, session_id):
            await bus.publish(run_id, ev)
            if isinstance(ev, dict):
                provider = ev.get("provider") or provider
                model = ev.get("model") or model
                if ev.get("type") not in _VOLATILE_EVENT_TYPES:
                    store_mod.record_event(run_id, ev.get("type", ""), ev.get("content", ""), ev.get("tool"))
        status = "done"
    except Exception as e:  # noqa: BLE001 - surface the failure to the client + store
        await bus.publish(run_id, {"type": "error", "content": str(e)[:300]})
    finally:
        try:
            cost = cost_tracker.run_stats()
        except Exception:  # pragma: no cover - cost is best-effort
            cost = {}
        store_mod.finish_run(run_id, status, provider, model, cost)
        # Always close the stream so every subscriber terminates cleanly.
        await bus.publish(run_id, runbus.END)
    return {"run_id": run_id, "status": status}


class WorkerSettings:  # pragma: no cover - requires arq runtime
    functions = [run_swarm_job]

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings
        return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
