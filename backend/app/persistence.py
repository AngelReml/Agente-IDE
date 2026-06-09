"""
Pluggable persistence backend (Fase 2).

Default is the local SQLite store (`store.py`, ships and is tested). Set
SWARM_DB=postgres + DATABASE_URL to use the Postgres backend (SQLAlchemy), which
is the horizontal-scale path. Selection degrades to SQLite if Postgres deps or
connection are unavailable, so local always works.

New platform code calls `get_backend()`; legacy code keeps calling `store`
directly (both target the same SQLite db locally).
"""
import logging
from functools import lru_cache

from . import config, store

logger = logging.getLogger(__name__)


class SqliteBackend:
    name = "sqlite"
    init = staticmethod(store.init)
    start_run = staticmethod(store.start_run)
    record_event = staticmethod(store.record_event)
    finish_run = staticmethod(store.finish_run)
    list_runs = staticmethod(store.list_runs)
    get_run_events = staticmethod(store.get_run_events)


class PostgresBackend:
    """SQLAlchemy-backed store. Requires `sqlalchemy` + `psycopg`. Same surface as
    SqliteBackend. Kept import-light so the module loads without those deps."""
    name = "postgres"

    def __init__(self, url: str):
        from sqlalchemy import create_engine  # imported lazily to keep deps optional
        self.engine = create_engine(url, pool_pre_ping=True, future=True)
        self._ensure_schema()

    def _ensure_schema(self):
        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running', provider TEXT, model TEXT,
                input_tokens INT DEFAULT 0, output_tokens INT DEFAULT 0, cost_usd DOUBLE PRECISION DEFAULT 0,
                started_at DOUBLE PRECISION NOT NULL, ended_at DOUBLE PRECISION)"""))
            c.execute(text("""CREATE TABLE IF NOT EXISTS events (
                id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL, ts DOUBLE PRECISION NOT NULL,
                type TEXT NOT NULL, tool TEXT, content TEXT)"""))

    def init(self):  # pragma: no cover - requires pg
        self._ensure_schema()

    def start_run(self, run_id, session_id, task):  # pragma: no cover
        import time

        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO runs (id, session_id, task, status, started_at) "
                           "VALUES (:i,:s,:t,'running',:ts) ON CONFLICT (id) DO NOTHING"),
                      dict(i=run_id, s=session_id, t=task, ts=time.time()))

    def record_event(self, run_id, etype, content="", tool=None):  # pragma: no cover
        import time

        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO events (run_id, ts, type, tool, content) VALUES (:r,:ts,:e,:to,:c)"),
                      dict(r=run_id, ts=time.time(), e=etype, to=tool, c=(content or "")[:4000]))

    def finish_run(self, run_id, status, provider, model, cost):  # pragma: no cover
        import time

        from sqlalchemy import text
        with self.engine.begin() as c:
            c.execute(text("UPDATE runs SET status=:s, provider=:p, model=:m, input_tokens=:it, "
                           "output_tokens=:ot, cost_usd=:cu, ended_at=:e WHERE id=:i"),
                      dict(s=status, p=provider, m=model, it=cost.get("input_tokens", 0),
                           ot=cost.get("output_tokens", 0), cu=cost.get("cost_usd", 0.0),
                           e=time.time(), i=run_id))

    def list_runs(self, session_id=None, limit=50):  # pragma: no cover
        from sqlalchemy import text
        q = "SELECT * FROM runs" + (" WHERE session_id=:s" if session_id else "") + " ORDER BY started_at DESC LIMIT :l"
        with self.engine.begin() as c:
            rows = c.execute(text(q), dict(s=session_id, l=limit)).mappings().all()
        return [dict(r) for r in rows]

    def get_run_events(self, run_id, limit=2000):  # pragma: no cover
        from sqlalchemy import text
        with self.engine.begin() as c:
            rows = c.execute(text("SELECT ts,type,tool,content FROM events WHERE run_id=:r ORDER BY id LIMIT :l"),
                             dict(r=run_id, l=limit)).mappings().all()
        return [dict(r) for r in rows]


@lru_cache(maxsize=1)
def get_backend():
    if config.db_backend() == "postgres" and config.database_url():
        # Fail FAST: do not silently fall back to a local SQLite that would diverge
        # from the shared DB and lose data across instances. Raising leaves the
        # lru_cache empty (it doesn't cache exceptions), so a later call retries
        # once Postgres is reachable again.
        be = PostgresBackend(config.database_url())
        logger.info("Persistence backend: postgres")
        return be
    return SqliteBackend()
