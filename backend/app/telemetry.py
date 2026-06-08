"""
Observability: distributed tracing of agent steps + structured logging.

Uses OpenTelemetry if it's installed; otherwise every primitive degrades to a
no-op so the app runs locally with zero extra dependencies (Fase Q / Fase 6).
"""
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("swarm.telemetry")

try:  # optional dependency
    from opentelemetry import trace as _otel_trace  # type: ignore
    _tracer = _otel_trace.get_tracer("swarm-ide")
    _HAS_OTEL = True
except Exception:  # pragma: no cover - optional
    _tracer = None
    _HAS_OTEL = False


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@contextmanager
def span(name: str, **attrs) -> Iterator[dict]:
    """Trace a unit of work. Yields a mutable dict for extra attributes.

    With OTel installed this creates a real span; without it, it just times the
    block and logs at debug level. Either way the call site is identical.
    """
    ctx: dict = dict(attrs)
    start = time.perf_counter()
    if _HAS_OTEL and _tracer is not None:
        with _tracer.start_as_current_span(name) as otel_span:
            try:
                yield ctx
            finally:
                for k, v in ctx.items():
                    try:
                        otel_span.set_attribute(k, v)
                    except Exception:
                        pass
    else:
        try:
            yield ctx
        finally:
            dur_ms = (time.perf_counter() - start) * 1000
            logger.debug("span %s %.1fms %s", name, dur_ms, ctx)


def event(name: str, **fields) -> None:
    """Structured log line (run_id / tool / etc. as fields)."""
    logger.info("%s %s", name, " ".join(f"{k}={v}" for k, v in fields.items()))


def enabled() -> bool:
    return _HAS_OTEL
