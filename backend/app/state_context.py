"""
Session context tracking using Python contextvars.
Isolated per-coroutine → safe in FastAPI async handlers.
"""
from contextvars import ContextVar
from typing import Set

# Whether the agent has read memoria.md in this session
memoria_read: ContextVar[bool] = ContextVar('memoria_read', default=False)

# Files mutated in this session
modified_files: ContextVar[Set[str]] = ContextVar('modified_files', default=frozenset())

# Whether a changelog entry was appended in this session
changelog_added: ContextVar[bool] = ContextVar('changelog_added', default=False)


def reset_session():
    """Call at the start of each task run to clear all session state."""
    memoria_read.set(False)
    modified_files.set(frozenset())
    changelog_added.set(False)


def mark_memoria_read() -> None:
    memoria_read.set(True)


def add_modified_file(path: str) -> None:
    current = modified_files.get()
    modified_files.set(current | {path})


def mark_changelog_added() -> None:
    changelog_added.set(True)


def get_modified_files() -> Set[str]:
    return modified_files.get()


def was_memoria_read() -> bool:
    return memoria_read.get()


def was_changelog_added() -> bool:
    return changelog_added.get()
