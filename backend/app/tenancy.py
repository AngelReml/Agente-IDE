"""
Multi-tenant data layer (Fase 3): users, workspaces, memberships, cost quotas and
an audit log — in SQLite (the Postgres path mirrors the schema). Plus the pure
workspace path-confinement used to keep one tenant's filesystem isolated.

Designed to be instantiated with an explicit db path so it is fully unit-testable.
"""
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

from . import config, auth


def resolve_in_workspace(workspace_root: str, path: str) -> str:
    """Confine `path` to `workspace_root`. Raises ValueError on escape (pure)."""
    root = os.path.realpath(workspace_root)
    rel = path.lstrip("/\\")
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"Ruta fuera del workspace: {path}")
    return target


@dataclass
class Workspace:
    id: str
    name: str
    root_path: str
    owner_id: str
    budget_usd: float


class TenancyDB:
    def __init__(self, db_path: str | None = None):
        self.path = db_path or os.path.join(config.project_root(), ".swarm", "tenancy.db")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT, created_at REAL);
            CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, name TEXT, root_path TEXT,
                owner_id TEXT, budget_usd REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS memberships (user_id TEXT, workspace_id TEXT, role TEXT,
                PRIMARY KEY (user_id, workspace_id));
            CREATE TABLE IF NOT EXISTS usage (workspace_id TEXT, ts REAL, cost_usd REAL,
                input_tokens INTEGER, output_tokens INTEGER);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
                user_id TEXT, workspace_id TEXT, action TEXT, detail TEXT);
            """)

    # ── Users ──
    def create_user(self, name: str) -> str:
        uid = uuid.uuid4().hex[:12]
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO users (id, name, created_at) VALUES (?,?,?)", (uid, name, time.time()))
        return uid

    def get_user(self, user_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(r) if r else None

    # ── Workspaces ──
    def create_workspace(self, name: str, root_path: str, owner_id: str, budget_usd: float = 0.0) -> str:
        wid = uuid.uuid4().hex[:12]
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO workspaces (id, name, root_path, owner_id, budget_usd) VALUES (?,?,?,?,?)",
                      (wid, name, root_path, owner_id, budget_usd))
            c.execute("INSERT OR REPLACE INTO memberships (user_id, workspace_id, role) VALUES (?,?, 'owner')",
                      (owner_id, wid))
        return wid

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            return Workspace(r["id"], r["name"], r["root_path"], r["owner_id"], r["budget_usd"]) if r else None

    def add_member(self, user_id: str, workspace_id: str, role: str) -> None:
        if role not in auth.ROLES:
            raise ValueError(f"Rol inválido: {role}")
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO memberships (user_id, workspace_id, role) VALUES (?,?,?)",
                      (user_id, workspace_id, role))

    def role_of(self, user_id: str, workspace_id: str) -> str | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT role FROM memberships WHERE user_id=? AND workspace_id=?",
                          (user_id, workspace_id)).fetchone()
            return r["role"] if r else None

    def workspaces_for(self, user_id: str) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT w.* FROM workspaces w JOIN memberships m ON w.id=m.workspace_id WHERE m.user_id=?",
                (user_id,)).fetchall()
            return [dict(r) for r in rows]

    # ── Usage / quota ──
    def record_usage(self, workspace_id: str, cost_usd: float, input_tokens: int, output_tokens: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO usage (workspace_id, ts, cost_usd, input_tokens, output_tokens) VALUES (?,?,?,?,?)",
                      (workspace_id, time.time(), cost_usd, input_tokens, output_tokens))

    def usage_total(self, workspace_id: str) -> float:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT COALESCE(SUM(cost_usd),0) AS t FROM usage WHERE workspace_id=?",
                          (workspace_id,)).fetchone()
            return float(r["t"])

    def check_budget(self, workspace_id: str) -> dict:
        ws = self.get_workspace(workspace_id)
        budget = ws.budget_usd if ws else 0.0
        used = self.usage_total(workspace_id)
        remaining = (budget - used) if budget > 0 else float("inf")
        return {"budget": budget, "used": round(used, 6), "remaining": remaining,
                "ok": budget <= 0 or used < budget}

    # ── Audit ──
    def audit(self, user_id: str, workspace_id: str, action: str, detail: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO audit (ts, user_id, workspace_id, action, detail) VALUES (?,?,?,?,?)",
                      (time.time(), user_id, workspace_id, action, detail[:500]))

    def audit_log(self, workspace_id: str, limit: int = 100) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT ts, user_id, action, detail FROM audit WHERE workspace_id=? "
                             "ORDER BY id DESC LIMIT ?", (workspace_id, limit)).fetchall()
            return [dict(r) for r in rows]


_default: TenancyDB | None = None


def db() -> TenancyDB:
    global _default
    if _default is None:
        _default = TenancyDB()
    return _default
