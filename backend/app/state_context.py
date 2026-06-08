"""
Session mutation tracking for the State Guard.

v3 used contextvars, but LangChain runs sync tools in a threadpool that *copies*
the context, so writes made inside a tool never propagated back to the streaming
coroutine — the guard never fired. We use a lock-protected module registry that
is reset at the start of every run and is visible across threads.
"""
import threading

_lock = threading.Lock()
_memoria_read = False
_modified_files: set[str] = set()
_changelog_added = False


def reset_session() -> None:
    global _memoria_read, _modified_files, _changelog_added
    with _lock:
        _memoria_read = False
        _modified_files = set()
        _changelog_added = False


def mark_memoria_read() -> None:
    global _memoria_read
    with _lock:
        _memoria_read = True


def add_modified_file(path: str) -> None:
    with _lock:
        _modified_files.add(path)


def mark_changelog_added() -> None:
    global _changelog_added
    with _lock:
        _changelog_added = True


def get_modified_files() -> set[str]:
    with _lock:
        return set(_modified_files)


def was_memoria_read() -> bool:
    with _lock:
        return _memoria_read


def was_changelog_added() -> bool:
    with _lock:
        return _changelog_added
