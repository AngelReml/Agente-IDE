"""
Repo retrieval (Fase 4).

A dependency-free TF-IDF retriever so the swarm can be handed *relevant* code
chunks instead of a raw file dump — better quality and lower token cost. The
`Retriever` interface leaves room for an embeddings backend (pgvector) later; the
TF-IDF implementation works offline today and is fully unit-tested.
"""
import hashlib
import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from . import config

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for w in _TOKEN_RE.findall(text):  # keep original case for camelCase splitting
        lw = w.lower()
        toks.append(lw)
        # split snake_case and camelCase into subtokens for better recall
        toks.extend(p for p in lw.split("_") if p)
        toks.extend(p.lower() for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", w) if len(p) > 1)
    return toks


@dataclass
class Chunk:
    path: str
    start_line: int
    text: str


@dataclass
class Hit:
    path: str
    start_line: int
    score: float
    snippet: str


class Retriever(Protocol):
    """Pluggable retrieval interface. TF-IDF today; an embeddings backend (Fase 4)
    can implement the same surface without touching callers."""

    def add(self, path: str, content: str) -> None: ...
    def add_chunks(self, path: str, chunks: list[tuple[int, str]]) -> None: ...
    def query(self, q: str, k: int = 5) -> list[Hit]: ...


def symbol_chunks(content: str, ext: str, max_lines: int = 80) -> list[tuple[int, str]]:
    """Chunk source along function/class boundaries (via the AST indexer) instead
    of fixed line windows — semantically coherent chunks rank better and embed
    better. Falls back to fixed windows for files without detectable symbols.
    Returns a list of (start_line, text)."""
    lines = content.splitlines()
    syms: list[dict] = []
    if ext in config.INDEXED_EXTS:
        try:
            from . import ast_indexer
            syms = sorted(ast_indexer.symbols_for(content, ext), key=lambda s: int(s.get("line", 1)))
        except Exception:
            syms = []
    if not syms:
        return [(i + 1, "\n".join(lines[i:i + 40])) for i in range(0, max(1, len(lines)), 40)]

    boundaries = sorted({max(1, int(s.get("line", 1))) for s in syms})
    chunks: list[tuple[int, str]] = []
    if boundaries[0] > 1:  # leading block (imports, module docstring…)
        head = "\n".join(lines[: boundaries[0] - 1])
        if head.strip():
            chunks.append((1, head))
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] - 1 if idx + 1 < len(boundaries) else len(lines)
        block = lines[start - 1:end]
        for off in range(0, max(1, len(block)), max_lines):  # split oversized symbols
            sub = "\n".join(block[off:off + max_lines])
            if sub.strip():
                chunks.append((start + off, sub))
    return chunks


class TfidfRetriever:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._n = 0

    def add_chunks(self, path: str, chunks: list[tuple[int, str]]) -> None:
        for start_line, block in chunks:
            if not block.strip():
                continue
            tf = Counter(tokenize(block))
            self._chunks.append(Chunk(path, start_line, block))
            self._tf.append(tf)
            for term in tf:
                self._df[term] += 1
            self._n += 1

    def add(self, path: str, content: str, chunk_lines: int = 40) -> None:
        lines = content.splitlines()
        chunks = [(i + 1, "\n".join(lines[i:i + chunk_lines]))
                  for i in range(0, max(1, len(lines)), chunk_lines)]
        self.add_chunks(path, chunks)

    def _idf(self, term: str) -> float:
        return math.log((1 + self._n) / (1 + self._df.get(term, 0))) + 1.0

    def query(self, q: str, k: int = 5) -> list[Hit]:
        qterms = Counter(tokenize(q))
        if not qterms or self._n == 0:
            return []
        scored: list[Hit] = []
        for chunk, tf in zip(self._chunks, self._tf, strict=True):
            score = 0.0
            for term, qc in qterms.items():
                if term in tf:
                    score += (tf[term]) * self._idf(term) * qc
            if score > 0:
                snippet = "\n".join(chunk.text.splitlines()[:8])
                scored.append(Hit(chunk.path, chunk.start_line, round(score, 4), snippet))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


def make_retriever() -> Retriever:
    """Select the retrieval backend by flag. TF-IDF today; 'embeddings' (Fase 4)
    falls back to TF-IDF until implemented (so the flag is safe to set early)."""
    if config.retrieval_backend() == "embeddings":
        logger.info("SWARM_RETRIEVAL=embeddings aún no implementado (Fase 4); usando TF-IDF.")
    return TfidfRetriever()


def build_repo_retriever(root: str, max_files: int = 400) -> Retriever:
    r = make_retriever()
    count = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in config.INDEXED_EXTS:
                continue
            fp = os.path.join(dirpath, fname)
            try:
                if os.path.getsize(fp) > 200_000:
                    continue
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    # Chunk along symbol boundaries instead of fixed windows.
                    r.add_chunks(os.path.relpath(fp, root), symbol_chunks(f.read(), ext))
            except OSError:
                continue
            count += 1
            if count >= max_files:
                return r
    return r


# ── Cached retriever (rebuilding on every query was O(repo) per call) ───────────

_CACHE: dict[str, tuple[str, Retriever]] = {}
_CACHE_LOCK = threading.Lock()


def _repo_signature(root: str, max_files: int = 400) -> str:
    """Cheap stat-only fingerprint (path:mtime:size). Changes when any indexed
    file is added/removed/edited, so we can reuse the built index otherwise."""
    parts: list[str] = []
    count = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in config.INDEXED_EXTS:
                continue
            fp = os.path.join(dirpath, fname)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            parts.append(f"{os.path.relpath(fp, root)}:{int(st.st_mtime)}:{st.st_size}")
            count += 1
            if count >= max_files:
                break
        if count >= max_files:
            break
    return hashlib.sha1("|".join(sorted(parts)).encode()).hexdigest()


def get_repo_retriever(root: str, max_files: int = 400) -> Retriever:
    """Return a cached retriever for `root`, rebuilding only when files changed."""
    sig = _repo_signature(root, max_files)
    with _CACHE_LOCK:
        cached = _CACHE.get(root)
        if cached and cached[0] == sig:
            return cached[1]
    r = build_repo_retriever(root, max_files)
    with _CACHE_LOCK:
        _CACHE[root] = (sig, r)
    return r


def retrieve_context(query: str, root: str | None = None, k: int = 5) -> str:
    root = root or config.project_root()
    hits = get_repo_retriever(root).query(query, k)
    if not hits:
        return ""
    out = ["CONTEXTO RELEVANTE (retrieval):"]
    for h in hits:
        out.append(f"\n📄 {h.path}:{h.start_line}  (score {h.score})\n{h.snippet}")
    return "\n".join(out)
