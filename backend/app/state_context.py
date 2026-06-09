"""
Per-session mutation tracking for the State Guard.

v3 used contextvars, but LangChain runs sync tools in a threadpool that *copies*
the context, so writes made inside a tool never propagated back to the streaming
coroutine — the guard never fired. We use a lock-protected registry, visible
across threads, **keyed by the current session**.

The session key travels via a ContextVar that LangChain's `run_in_executor`
copies INTO the tool thread (verified), so a tool always writes to its own
session's bucket; the dict + lock make those writes visible back to the
coroutine. Concurrent sessions no longer clobber each other's tracking.
"""
import contextvars
import threading

_lock = threading.Lock()
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar("swarm_session", default="default")


class _State:
    __slots__ = ("memoria_read", "modified_files", "changelog_added")

    def __init__(self) -> None:
        self.memoria_read = False
        self.modified_files: set[str] = set()
        self.changelog_added = False


_registry: dict[str, _State] = {}


def set_session(session_id: str | None) -> contextvars.Token:
    """Bind the current execution context to a session. Call at run start so the
    tools (in the threadpool) record into the right session's bucket."""
    return _current_session.set(session_id or "default")


def _bucket(sid: str) -> _State:  # must be called under _lock
    st = _registry.get(sid)
    if st is None:
        st = _State()
        _registry[sid] = st
    return st


def reset_session() -> None:
    sid = _current_session.get()
    with _lock:
        _registry[sid] = _State()


def clear_session(session_id: str) -> None:
    """Drop a session's bucket entirely (e.g. when the session is purged)."""
    with _lock:
        _registry.pop(session_id or "default", None)


def mark_memoria_read() -> None:
    sid = _current_session.get()
    with _lock:
        _bucket(sid).memoria_read = True


def add_modified_file(path: str) -> None:
    sid = _current_session.get()
    with _lock:
        _bucket(sid).modified_files.add(path)


def mark_changelog_added() -> None:
    sid = _current_session.get()
    with _lock:
        _bucket(sid).changelog_added = True


def get_modified_files() -> set[str]:
    sid = _current_session.get()
    with _lock:
        return set(_bucket(sid).modified_files)


def was_memoria_read() -> bool:
    sid = _current_session.get()
    with _lock:
        return _bucket(sid).memoria_read


def was_changelog_added() -> bool:
    sid = _current_session.get()
    with _lock:
        return _bucket(sid).changelog_added
