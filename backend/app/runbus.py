"""
Cross-process run event bus (Fase 6, paso 4 — ejecución out-of-process).

When the swarm runs in a dedicated Arq worker (the only process with Docker/proxy
access), the worker publishes each run event here and the API tails them to the SSE
client. The transport is an **ordered, replayable log with a blocking tail** — not
pub/sub + a separate backlog — so a late/reconnecting subscriber reads from offset 0
and then follows live, with no lost-event or duplicate races.

Backends, selected by REDIS_URL:
  • InProcessBus — an in-memory log per run (used by tests; never crosses processes).
  • RedisBus — a Redis Stream per run (XADD to publish, XREAD BLOCK to tail).

The local single-user path does NOT use the bus: RunManager runs in-process and
streams from its own buffer. This module stays inert unless REDIS_URL is set.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from functools import lru_cache

from . import config

logger = logging.getLogger(__name__)

# Terminal sentinel appended by the producer; ends every subscriber's stream.
END = {"type": "_end"}


def _is_end(ev: dict) -> bool:
    return isinstance(ev, dict) and ev.get("type") == "_end"


class _Topic:
    """An append-only event log for one run, with a condition to wake tailers."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.closed = False
        self.cond = asyncio.Condition()


class InProcessBus:
    name = "inprocess"

    def __init__(self) -> None:
        self._topics: dict[str, _Topic] = {}

    def _topic(self, run_id: str) -> _Topic:
        return self._topics.setdefault(run_id, _Topic())

    async def publish(self, run_id: str, ev: dict) -> None:
        t = self._topic(run_id)
        async with t.cond:
            t.events.append(ev)
            if _is_end(ev):
                t.closed = True
            t.cond.notify_all()

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict, None]:
        t = self._topic(run_id)
        i = 0
        while True:
            async with t.cond:
                while i >= len(t.events) and not t.closed:
                    await t.cond.wait()
                batch = t.events[i:]
                i = len(t.events)
                closed = t.closed
            for ev in batch:
                if _is_end(ev):
                    return
                yield ev
            if closed:
                return


class RedisBus:  # pragma: no cover - requires a live Redis to exercise
    """Redis Stream per run: XADD publishes, XREAD BLOCK tails from offset 0 (full
    replay) then follows live. MAXLEN+EXPIRE bound memory/TTL so finished runs are
    reclaimed. Decodes work whether the client returns bytes or str."""

    name = "redis"

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis = None

    async def _client(self):
        if self._redis is None:
            from redis.asyncio import Redis
            self._redis = Redis.from_url(self._url)
        return self._redis

    @staticmethod
    def _key(run_id: str) -> str:
        return f"swarm:run:{run_id}"

    @staticmethod
    def _field(fields, name: str):
        return fields.get(name) or fields.get(name.encode("utf-8"))

    async def publish(self, run_id: str, ev: dict) -> None:
        r = await self._client()
        key = self._key(run_id)
        await r.xadd(key, {"data": json.dumps(ev, ensure_ascii=False)},
                     maxlen=config.RUN_EVENT_BUFFER, approximate=True)
        await r.expire(key, 3600)  # reclaim the stream an hour after the last event

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict, None]:
        r = await self._client()
        key = self._key(run_id)
        last = "0"  # from the beginning → replay backlog, then live tail
        while True:
            resp = await r.xread({key: last}, block=15000, count=200)
            if not resp:
                continue  # block timeout heartbeat; the producer always emits _end
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    last = entry_id
                    raw = self._field(fields, "data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    ev = json.loads(raw)
                    if _is_end(ev):
                        return
                    yield ev


@lru_cache(maxsize=1)
def get_bus():
    """RedisBus when REDIS_URL + redis are present, else InProcessBus."""
    url = config.redis_url()
    if url:
        try:
            import redis.asyncio  # noqa: F401
            logger.info("Run bus: redis")
            return RedisBus(url)
        except Exception as e:  # pragma: no cover - import/parse failure
            logger.warning("redis no disponible (%s) — run bus in-process", e)
    return InProcessBus()
