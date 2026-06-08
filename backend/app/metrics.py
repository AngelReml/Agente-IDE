"""
Metrics + request correlation (Fase 6).

A tiny in-process metrics registry that renders Prometheus text format (no extra
deps; the OTel exporter in `telemetry.py` is the richer path). Plus a request-id
helper for log correlation. Render output is unit-tested.
"""
import threading
import uuid


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[tuple, float] = {}
        self._gauges: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, **labels) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._gauges[key] = value

    def value(self, name: str, **labels) -> float:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            return self._counters.get(key, self._gauges.get(key, 0.0))

    def render(self) -> str:
        def fmt(labels: tuple) -> str:
            if not labels:
                return ""
            return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
        lines: list[str] = []
        with self._lock:
            for (name, labels), val in sorted(self._counters.items(), key=lambda x: x[0][0]):
                lines.append(f"{name}{fmt(labels)} {val}")
            for (name, labels), val in sorted(self._gauges.items(), key=lambda x: x[0][0]):
                lines.append(f"{name}{fmt(labels)} {val}")
        return "\n".join(lines) + "\n"


M = Metrics()


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
