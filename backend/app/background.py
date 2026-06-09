"""
Background / scheduled agents (Fase 5).

A registry of long-running or scheduled agent tasks ("each morning, triage the
issue tracker"). This is the in-memory foundation with the full CRUD surface; the
production path persists rows and a scheduler ticks them (cron). Fully unit-tested.
"""
from __future__ import annotations  # method named `list` would shadow builtin in annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class BackgroundTask:
    id: str
    name: str
    prompt: str
    schedule: str = ""          # cron expr or "interval:3600" or "" (manual)
    enabled: bool = True
    last_run: float | None = None
    created_at: float = field(default_factory=time.time)


class BackgroundRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def register(self, name: str, prompt: str, schedule: str = "") -> str:
        tid = uuid.uuid4().hex[:12]
        with self._lock:
            self._tasks[tid] = BackgroundTask(id=tid, name=name, prompt=prompt, schedule=schedule)
        return tid

    def get(self, tid: str) -> BackgroundTask | None:
        with self._lock:
            return self._tasks.get(tid)

    def list(self) -> list[dict]:
        with self._lock:
            return [asdict(t) for t in self._tasks.values()]

    def set_enabled(self, tid: str, enabled: bool) -> bool:
        with self._lock:
            t = self._tasks.get(tid)
            if not t:
                return False
            t.enabled = enabled
            return True

    def mark_run(self, tid: str) -> None:
        with self._lock:
            t = self._tasks.get(tid)
            if t:
                t.last_run = time.time()

    def remove(self, tid: str) -> bool:
        with self._lock:
            return self._tasks.pop(tid, None) is not None

    def due(self, now: float | None = None) -> list[BackgroundTask]:
        """Interval-scheduled tasks whose interval has elapsed (cron left to the
        production scheduler). Pure enough to test."""
        now = now or time.time()
        out = []
        with self._lock:
            for t in self._tasks.values():
                if not t.enabled or not t.schedule.startswith("interval:"):
                    continue
                try:
                    every = float(t.schedule.split(":", 1)[1])
                except ValueError:
                    continue
                if t.last_run is None or (now - t.last_run) >= every:
                    out.append(t)
        return out


REGISTRY = BackgroundRegistry()
