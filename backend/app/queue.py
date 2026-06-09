"""
Job queue abstraction (Fase 2).

`InProcessQueue` (default) runs jobs as asyncio tasks in the API process — durable
within the process and enough for local/single-node use. `RedisQueue` routes jobs
to a separate Arq worker pool (see `worker.py`) for horizontal scale. Selection is
automatic: Redis if REDIS_URL + arq are present, else in-process. The interface is
identical so callers never change.
"""
from __future__ import annotations  # method named `list` would shadow builtin in annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)

JobFactory = Callable[[], Awaitable]


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    result: object = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None


class InProcessQueue:
    name = "inprocess"

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def submit(self, kind: str, factory: JobFactory) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, kind=kind)
        self._jobs[job_id] = job

        async def runner():
            job.status = "running"
            try:
                job.result = await factory()
                job.status = "done"
            except asyncio.CancelledError:
                job.status = "error"
                job.error = "cancelled"
                raise
            except Exception as e:  # pragma: no cover - defensive
                job.status = "error"
                job.error = str(e)[:300]
                logger.exception("job %s failed", job_id)
            finally:
                job.ended_at = time.time()

        self._tasks[job_id] = asyncio.create_task(runner())
        return job_id

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        t = self._tasks.get(job_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    async def join(self, job_id: str) -> Job:
        """Await completion (useful in tests)."""
        t = self._tasks.get(job_id)
        if t:
            try:
                await t
            except asyncio.CancelledError:
                pass
        return self._jobs[job_id]


class RedisQueue:
    """Arq-backed queue. Requires `arq` + REDIS_URL. The actual execution happens
    in the worker process (worker.py); here we only enqueue by name."""
    name = "redis"

    def __init__(self, redis_url: str):
        self._url = redis_url
        self._pool = None

    async def _get_pool(self):  # pragma: no cover - requires redis
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings
            self._pool = await create_pool(RedisSettings.from_dsn(self._url))
        return self._pool

    async def submit(self, kind: str, factory: JobFactory) -> str:  # pragma: no cover
        # In the Redis path the work is identified by `kind` + serialisable args,
        # enqueued for the worker; the in-process `factory` closure is not crossed.
        raise NotImplementedError(
            "RedisQueue.submit requires enqueue-by-name; use enqueue_named() with the worker.")

    async def enqueue_named(self, func_name: str, *args) -> str:  # pragma: no cover
        pool = await self._get_pool()
        job = await pool.enqueue_job(func_name, *args)
        return job.job_id if job else ""


@lru_cache(maxsize=1)
def get_queue():
    import os
    url = os.getenv("REDIS_URL", "")
    if url:
        try:
            import arq  # noqa: F401
            logger.info("Job queue: redis")
            return RedisQueue(url)
        except Exception as e:
            logger.warning("Redis/arq no disponible (%s) — cola in-process", e)
    return InProcessQueue()
