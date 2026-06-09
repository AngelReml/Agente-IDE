"""
Repo retrieval (Fase 4).

A dependency-free TF-IDF retriever so the swarm can be handed *relevant* code
chunks instead of a raw file dump — better quality and lower token cost. The
`Retriever` interface leaves room for an embeddings backend (pgvector) later; the
TF-IDF implementation works offline today and is fully unit-tested.
"""
import hashlib
import json
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


# ── Embeddings backend (Fase 4): semantic retrieval ─────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class _EmbedCache:
    """Persistent chunk→vector cache keyed by sha1(text): unchanged code is never
    re-embedded across rebuilds (saves API cost and latency)."""

    def __init__(self, root: str) -> None:
        self._path = os.path.join(root, ".swarm", "embeddings_cache.json")
        self._data: dict[str, list[float]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        self._load()
        return self._data.get(self._key(text))

    def put_many(self, pairs) -> None:
        self._load()
        for text, vec in pairs:
            self._data[self._key(text)] = vec

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f)
        except Exception:
            logger.debug("could not persist embedding cache", exc_info=True)


# ── Vector stores: where chunk embeddings live (Fase 7) ─────────────────────────

class VectorStore(Protocol):
    """Pluggable storage+search for chunk vectors. MemoryVectorStore (local) keeps
    them in-process; PgVectorStore (platform) persists them in Postgres/pgvector."""

    def add(self, items: list[tuple[str, int, str, list[float]]]) -> None: ...
    def search(self, qvec: list[float], k: int) -> list[Hit]: ...


class MemoryVectorStore:
    """In-process store: a list of vectors ranked by cosine. Fine up to ~10⁴ chunks
    and needs no infra — the default for the local/single-user path."""

    name = "memory"

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vecs: list[list[float]] = []

    def add(self, items: list[tuple[str, int, str, list[float]]]) -> None:
        for path, start_line, text, vec in items:
            self._chunks.append(Chunk(path, start_line, text))
            self._vecs.append(vec)

    def search(self, qvec: list[float], k: int) -> list[Hit]:
        scored: list[Hit] = []
        for chunk, v in zip(self._chunks, self._vecs, strict=True):
            score = _cosine(qvec, v)
            if score > 0:
                snippet = "\n".join(chunk.text.splitlines()[:8])
                scored.append(Hit(chunk.path, chunk.start_line, round(score, 4), snippet))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


class PgVectorStore:
    """Persistent store on the existing Postgres via the `pgvector` extension.
    Scales beyond memory and is shared across API/worker processes. Rows are keyed
    by `namespace` (one repo/workspace) so several repos coexist in one table.
    `conn` is injectable for unit tests (no live DB needed)."""

    name = "pgvector"

    def __init__(self, dsn: str | None = None, dim: int | None = None,
                 namespace: str = "default", conn=None) -> None:
        self._dsn = dsn or config.database_url()
        self._dim = dim or config.embedding_dim()
        self._ns = namespace
        self._conn = conn
        self._ready = False

    @staticmethod
    def _libpq_dsn(dsn: str) -> str:
        """Strip the SQLAlchemy driver suffix: persistence shares DATABASE_URL as
        `postgresql+psycopg://…`, but psycopg.connect() speaks raw libpq and rejects
        the `+psycopg` part. Without this, pgvector silently falls back to memory."""
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres+psycopg://"):
            if dsn.startswith(prefix):
                return "postgresql://" + dsn[len(prefix):]
        return dsn

    def _connection(self):
        if self._conn is None:
            import psycopg
            self._conn = psycopg.connect(self._libpq_dsn(self._dsn))
        return self._conn

    @staticmethod
    def _lit(vec: list[float]) -> str:
        """pgvector text literal: '[0.1,0.2,…]' (cast with ::vector in SQL)."""
        return "[" + ",".join(repr(float(x)) for x in vec) + "]"

    def _ensure(self) -> None:
        if self._ready:
            return
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS swarm_chunks ("
                "namespace TEXT, path TEXT, start_line INT, text TEXT, "
                f"embedding vector({self._dim}))")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS swarm_chunks_emb_idx ON swarm_chunks "
                "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
        conn.commit()
        self._ready = True

    def add(self, items: list[tuple[str, int, str, list[float]]]) -> None:
        if not items:
            return
        self._ensure()
        conn = self._connection()
        paths = sorted({p for p, _s, _t, _v in items})
        with conn.cursor() as cur:
            # Re-indexing a file replaces its previous chunks (incremental rebuilds).
            cur.execute("DELETE FROM swarm_chunks WHERE namespace=%s AND path = ANY(%s)",
                        (self._ns, paths))
            for path, start_line, text, vec in items:
                cur.execute(
                    "INSERT INTO swarm_chunks (namespace, path, start_line, text, embedding) "
                    "VALUES (%s,%s,%s,%s,%s::vector)",
                    (self._ns, path, start_line, text, self._lit(vec)))
        conn.commit()

    def search(self, qvec: list[float], k: int) -> list[Hit]:
        self._ensure()
        conn = self._connection()
        lit = self._lit(qvec)
        with conn.cursor() as cur:
            # `<=>` is cosine distance; similarity = 1 - distance (higher is better).
            cur.execute(
                "SELECT path, start_line, text, 1 - (embedding <=> %s::vector) AS score "
                "FROM swarm_chunks WHERE namespace=%s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (lit, self._ns, lit, k))
            rows = cur.fetchall()
        hits: list[Hit] = []
        for path, start_line, text, score in rows:
            snippet = "\n".join((text or "").splitlines()[:8])
            hits.append(Hit(path, start_line, round(float(score), 4), snippet))
        return hits


def _namespace(root: str) -> str:
    return hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:16]


def make_vector_store(namespace: str = "default") -> VectorStore:
    """Select the vector store by flag, falling back to memory if pgvector or its
    Postgres is unavailable — so SWARM_VECTOR_STORE=pgvector never breaks a run."""
    if config.vector_store() == "pgvector" and config.database_url():
        try:
            store = PgVectorStore(namespace=namespace)
            store._ensure()  # connect + create extension/table now; failure → fallback
            return store
        except Exception as e:
            logger.warning("PgVectorStore no disponible (%s); usando memoria.", e)
    return MemoryVectorStore()


def _openai_embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured OpenAI embedding model; records cost."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = config.embedding_model()
    resp = client.embeddings.create(model=model, input=texts)
    try:
        from . import cost_tracker
        cost_tracker.record("openai", model, getattr(resp.usage, "total_tokens", 0) or 0, 0)
    except Exception:
        pass
    return [d.embedding for d in resp.data]


class EmbeddingRetriever:
    """Semantic retriever: embeds symbol chunks and ranks by cosine similarity.
    `embed_fn` is injectable so it's unit-testable without network/cost."""

    name = "embeddings"

    def __init__(self, embed_fn=None, cache: _EmbedCache | None = None,
                 store: VectorStore | None = None) -> None:
        self._embed = embed_fn or _openai_embed
        self._cache = cache
        self._store: VectorStore = store or MemoryVectorStore()
        self._count = 0

    def add_chunks(self, path: str, chunks: list[tuple[int, str]]) -> None:
        blocks = [(s, t) for s, t in chunks if t.strip()]
        if not blocks:
            return
        vecs: list[list[float] | None] = []
        to_embed: list[str] = []
        idx_map: list[int] = []
        for i, (_s, t) in enumerate(blocks):
            cached = self._cache.get(t) if self._cache else None
            vecs.append(cached)
            if cached is None:
                idx_map.append(i)
                to_embed.append(t)
        if to_embed:
            fresh = self._embed(to_embed)  # one batched call for the uncached chunks
            for j, vec in zip(idx_map, fresh, strict=False):
                vecs[j] = vec
            if self._cache:
                self._cache.put_many(zip(to_embed, fresh, strict=False))
                self._cache.save()
        items = [(path, s, t, v) for (s, t), v in zip(blocks, vecs, strict=True) if v is not None]
        if items:
            self._store.add(items)
            self._count += len(items)

    def add(self, path: str, content: str) -> None:
        self.add_chunks(path, symbol_chunks(content, os.path.splitext(path)[1].lower()))

    def query(self, q: str, k: int = 5) -> list[Hit]:
        if self._count == 0:  # nothing indexed → skip the embed call (no network/cost)
            return []
        qv = self._embed([q])[0]
        return self._store.search(qv, k)


def make_retriever() -> Retriever:
    """Select the retrieval backend by flag. 'embeddings' needs OPENAI_API_KEY;
    without it (or on any error) it falls back to TF-IDF, so the flag is always safe."""
    if config.retrieval_backend() == "embeddings":
        if os.getenv("OPENAI_API_KEY"):
            try:
                root = config.project_root()
                return EmbeddingRetriever(cache=_EmbedCache(root),
                                          store=make_vector_store(_namespace(root)))
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("EmbeddingRetriever no disponible (%s); usando TF-IDF.", e)
        else:
            logger.info("SWARM_RETRIEVAL=embeddings sin OPENAI_API_KEY; usando TF-IDF.")
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
