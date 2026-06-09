"""
Per-run and per-session runtime state.

This is the module that fixes the "everything is a global" problem: instead of
mutable module-level variables that two concurrent /run requests clobber, each
run gets its own RunContext (router position, cost accumulator, loop detector).
A SessionManager keeps lightweight per-session metadata keyed by session id.
"""
import hashlib
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from . import config

# ── Loop detector (sliding window, fixes the "only compares to previous" bug) ───

class LoopDetector:
    """Detects a tool+args combo repeating too often within a recent window.

    Unlike the old version it inspects the last LOOP_WINDOW calls, so alternating
    patterns (A,B,A,B,…) and bursty repeats are both caught.
    """

    def __init__(self, window: int = config.LOOP_WINDOW):
        self._window: deque[str] = deque(maxlen=window)

    def reset(self) -> None:
        self._window.clear()

    def check(self, tool_name: str, tool_input: dict) -> int:
        raw = json.dumps(tool_input, sort_keys=True, default=str)
        key = f"{tool_name}:{hashlib.md5(raw.encode()).hexdigest()[:8]}"
        self._window.append(key)
        return self._window.count(key)


# ── Per-run cost accumulator ────────────────────────────────────────────────────

@dataclass
class RunCost:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, inp: int, out: int, cost: float) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.cost_usd += cost

    def stats(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


# ── Run context ─────────────────────────────────────────────────────────────────

@dataclass
class RunContext:
    run_id: str
    session_id: str
    task: str
    cost: RunCost = field(default_factory=RunCost)
    loop: LoopDetector = field(default_factory=LoopDetector)
    provider: str | None = None
    model: str | None = None
    started_at: float = field(default_factory=time.time)


# ── Session manager ─────────────────────────────────────────────────────────────

@dataclass
class Session:
    id: str
    # None means "inherit the process-wide default" (smart_router.get_routing_mode());
    # set explicitly to isolate this session's routing from others.
    routing_mode: str | None = None
    manual_model: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def consume_manual_model(self) -> str | None:
        """Return the pinned model once, then clear it (one-shot, like the global)."""
        m = self.manual_model
        self.manual_model = None
        return m


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        ttl = getattr(config, "SESSION_TTL_SECONDS", 6 * 3600)
        stale = [sid for sid, s in self._sessions.items()
                 if sid != "default" and now - s.last_active > ttl]
        for sid in stale:
            self._sessions.pop(sid, None)

    def get(self, session_id: str | None) -> Session:
        sid = session_id or "default"
        with self._lock:
            now = time.time()
            self._prune(now)  # bound memory: drop idle sessions
            sess = self._sessions.get(sid)
            if sess is None:
                sess = Session(id=sid)
                self._sessions[sid] = sess
            sess.last_active = now
            return sess

    def all(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())


SESSIONS = SessionManager()


def new_run(task: str, session_id: str | None = None) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4().hex[:12],
        session_id=session_id or "default",
        task=task,
    )
