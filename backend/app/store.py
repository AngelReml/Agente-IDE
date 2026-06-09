"""
Lightweight SQLite persistence for runs, events and cost.

Replaces the single fragile session_history.json with a real, queryable store
so runs survive restarts and can be listed/inspected. Thread-safe via a module
lock + per-call connections (SQLite handles concurrent readers fine).
"""
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _db_path() -> str:
    swarm_dir = os.path.join(config.project_root(), ".swarm")
    os.makedirs(swarm_dir, exist_ok=True)
    return os.path.join(swarm_dir, "swarm.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                task        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'running',
                provider    TEXT,
                model       TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd    REAL DEFAULT 0,
                started_at  REAL NOT NULL,
                ended_at    REAL
            );
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id    TEXT NOT NULL,
                ts        REAL NOT NULL,
                type      TEXT NOT NULL,
                tool      TEXT,
                content   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
            """
        )


def start_run(run_id: str, session_id: str, task: str) -> None:
    init()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, session_id, task, status, started_at) "
            "VALUES (?, ?, ?, 'running', ?)",
            (run_id, session_id, task, time.time()),
        )


def record_event(run_id: str, etype: str, content: str = "", tool: str | None = None) -> None:
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO events (run_id, ts, type, tool, content) VALUES (?, ?, ?, ?, ?)",
                (run_id, time.time(), etype, tool, (content or "")[:4000]),
            )
    except Exception:
        logger.debug("record_event failed for run %s", run_id, exc_info=True)


def finish_run(run_id: str, status: str, provider: str | None,
               model: str | None, cost: dict[str, Any]) -> None:
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "UPDATE runs SET status=?, provider=?, model=?, input_tokens=?, "
                "output_tokens=?, cost_usd=?, ended_at=? WHERE id=?",
                (status, provider, model,
                 cost.get("input_tokens", 0), cost.get("output_tokens", 0),
                 cost.get("cost_usd", 0.0), time.time(), run_id),
            )
    except Exception:
        logger.debug("finish_run failed for run %s", run_id, exc_info=True)


def list_runs(session_id: str | None = None, limit: int = 50) -> list[dict]:
    init()
    with _lock, _connect() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM runs WHERE session_id=? ORDER BY started_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_run_events(run_id: str, limit: int = 2000) -> list[dict]:
    init()
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT ts, type, tool, content FROM events WHERE run_id=? ORDER BY id ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Per-project session history (replaces session_history.json) ─────────────────

def _history_path() -> Path:
    p = Path(config.project_root()) / ".swarm"
    p.mkdir(parents=True, exist_ok=True)
    return p / "session_history.json"


def load_history_raw() -> list:
    try:
        path = _history_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_history_raw(data: list) -> None:
    try:
        _history_path().write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def clear_history() -> None:
    try:
        _history_path().unlink(missing_ok=True)
    except Exception:
        pass
