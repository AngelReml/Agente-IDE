"""
Repo retrieval (Fase 4).

A dependency-free TF-IDF retriever so the swarm can be handed *relevant* code
chunks instead of a raw file dump — better quality and lower token cost. The
`Retriever` interface leaves room for an embeddings backend (pgvector) later; the
TF-IDF implementation works offline today and is fully unit-tested.
"""
import hashlib
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass

from . import config

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


class TfidfRetriever:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._n = 0

    def add(self, path: str, content: str, chunk_lines: int = 40) -> None:
        lines = content.splitlines()
        for i in range(0, max(1, len(lines)), chunk_lines):
            block = "\n".join(lines[i:i + chunk_lines])
            if not block.strip():
                continue
            tf = Counter(tokenize(block))
            self._chunks.append(Chunk(path, i + 1, block))
            self._tf.append(tf)
            for term in tf:
                self._df[term] += 1
            self._n += 1

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


def build_repo_retriever(root: str, max_files: int = 400) -> TfidfRetriever:
    r = TfidfRetriever()
    count = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in config.INDEXED_EXTS:
                continue
            fp = os.path.join(dirpath, fname)
            try:
                if os.path.getsize(fp) > 200_000:
                    continue
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    r.add(os.path.relpath(fp, root), f.read())
            except OSError:
                continue
            count += 1
            if count >= max_files:
                return r
    return r


# ── Cached retriever (rebuilding on every query was O(repo) per call) ───────────

_CACHE: dict[str, tuple[str, "TfidfRetriever"]] = {}
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


def get_repo_retriever(root: str, max_files: int = 400) -> "TfidfRetriever":
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
