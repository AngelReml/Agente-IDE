"""
Import/dependency graph (Fase 5).

A lightweight static dependency graph over Python/JS/TS files, complementing the
symbol-level `ast_indexer`. Lets an agent (or the orchestrator) reason about blast
radius: "what imports this module?" before a risky change. Regex-based — no LSP
needed — and fully unit-tested at the parse level.
"""
import os
import re

from . import config

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))", re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:import\s+[^;'"]*?from\s+|require\(\s*|import\(\s*)['"]([^'"]+)['"]""")


def parse_imports(path: str, content: str) -> list[str]:
    ext = os.path.splitext(path)[1].lower()
    deps: set[str] = set()
    if ext == ".py":
        for m in _PY_IMPORT.finditer(content):
            deps.add(m.group(1) or m.group(2))
    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        for m in _JS_IMPORT.finditer(content):
            deps.add(m.group(1))
    return sorted(d for d in deps if d)


def build_graph(root: str | None = None) -> dict[str, list[str]]:
    root = root or config.project_root()
    graph: dict[str, list[str]] = {}
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in config.INDEXED_EXTS:
                continue
            full = os.path.join(dp, fname)
            rel = os.path.relpath(full, root)
            try:
                with open(full, encoding="utf-8", errors="ignore") as f:
                    graph[rel] = parse_imports(rel, f.read())
            except OSError:
                continue
    return graph


def dependents_of(graph: dict[str, list[str]], needle: str) -> list[str]:
    """Files whose imports reference `needle` (substring match on the import target)."""
    return sorted(f for f, deps in graph.items() if any(needle in d for d in deps))
