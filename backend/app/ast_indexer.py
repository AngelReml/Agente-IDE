"""
Semantic AST indexer for Python/JS/TS files.
Scans PROJECT_ROOT and stores a symbol map in .swarm/index.json.
"""
import os
import ast
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Any

INDEXED_EXTS = {'.py', '.ts', '.tsx', '.js', '.jsx'}
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".next",
    "venv", ".venv", ".mypy_cache", "dist", "build", ".cache", ".swarm"
})

_JS_PATTERNS = [
    (r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)', 'function'),
    (r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', 'arrow_fn'),
    (r'(?:export\s+)?(?:default\s+)?class\s+(\w+)', 'class'),
    (r'(?:export\s+)?(?:type|interface)\s+(\w+)', 'type'),
    (r'(?:export\s+)?const\s+(\w+):\s*React\.FC', 'component'),
    (r'export\s+function\s+(\w+)', 'export_fn'),
]


def _index_python(content: str, filepath: str) -> List[Dict[str, Any]]:
    symbols: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(content, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "kind": "function",
                    "name": node.name,
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "decorators": [
                        d.id if isinstance(d, ast.Name) else
                        d.attr if isinstance(d, ast.Attribute) else ""
                        for d in node.decorator_list
                    ],
                })
            elif isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                symbols.append({
                    "kind": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "methods": methods,
                })
    except SyntaxError:
        pass
    return symbols


def _index_js(content: str) -> List[Dict[str, Any]]:
    symbols: List[Dict[str, Any]] = []
    seen: set = set()
    for pattern, kind in _JS_PATTERNS:
        for m in re.finditer(pattern, content, re.MULTILINE):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = content[: m.start()].count('\n') + 1
            symbols.append({"kind": kind, "name": name, "line": line})
    return symbols


def build_index(project_root: str) -> Dict[str, Any]:
    index: Dict[str, Any] = {
        "generated_at": int(time.time()),
        "root": project_root,
        "files": {},
    }
    for root, dirs, files in os.walk(project_root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in INDEXED_EXTS:
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, project_root)
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception:
                continue
            symbols = _index_python(content, full_path) if ext == '.py' else _index_js(content)
            if symbols:
                index["files"][rel_path] = symbols
    return index


def save_index(project_root: str) -> str:
    swarm_dir = os.path.join(project_root, ".swarm")
    os.makedirs(swarm_dir, exist_ok=True)
    idx = build_index(project_root)
    idx_path = os.path.join(swarm_dir, "index.json")
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in idx["files"].values())
    return f"✅ Indexed {len(idx['files'])} files, {total} symbols → .swarm/index.json"


def load_index(project_root: str) -> Dict[str, Any]:
    idx_path = os.path.join(project_root, ".swarm", "index.json")
    if not os.path.exists(idx_path):
        return {}
    try:
        with open(idx_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def search_symbol(project_root: str, symbol: str) -> List[Dict[str, Any]]:
    idx = load_index(project_root)
    results = []
    sym_lower = symbol.lower()
    for fpath, symbols in idx.get("files", {}).items():
        for sym in symbols:
            if sym_lower in sym.get("name", "").lower():
                results.append({
                    "file": fpath,
                    "kind": sym.get("kind"),
                    "name": sym.get("name"),
                    "line": sym.get("line"),
                })
    return results


def format_semantic_map(project_root: str, max_files: int = 40) -> str:
    idx = load_index(project_root)
    if not idx:
        return "No hay índice semántico. Llama primero a get_semantic_map()."
    ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(idx.get('generated_at', 0)))
    lines = [f"🗺️ Mapa Semántico — {len(idx['files'])} archivos indexados ({ts})", ""]
    for i, (fpath, symbols) in enumerate(sorted(idx.get("files", {}).items())):
        if i >= max_files:
            lines.append(f"  ... y {len(idx['files']) - max_files} archivos más")
            break
        lines.append(f"📄 {fpath}  ({len(symbols)} símbolos)")
        for sym in symbols[:8]:
            kind = sym.get("kind", "?")
            name = sym.get("name", "?")
            line = sym.get("line", "?")
            icon = "🔷" if kind == "class" else "🔸"
            lines.append(f"   {icon} {kind}: {name} (L{line})")
        if len(symbols) > 8:
            lines.append(f"   … +{len(symbols) - 8} más")
    return "\n".join(lines)
