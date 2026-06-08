"""
Externalised, versioned prompts (closes audit finding Q3).

Prompts live as markdown files next to this module so they can be edited,
versioned and A/B-tested without touching Python. `load("system")` reads
`system.md`; results are cached but reload() clears the cache for hot iteration.
"""
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load(name: str) -> str:
    path = _DIR / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def reload() -> None:
    load.cache_clear()
