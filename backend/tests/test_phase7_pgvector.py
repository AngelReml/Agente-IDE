"""Phase 7 (architecture plan): pluggable vector store — MemoryVectorStore (local)
and PgVectorStore (Postgres/pgvector). The pgvector SQL is exercised against a fake
psycopg-style connection, so no live database is required."""
from app import retrieval


# ── A fake psycopg3 connection: records executed SQL + params, returns canned rows ──

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.conn.rows


class _FakeConn:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1


# ── Store selection ──────────────────────────────────────────────────────────────

def test_vector_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("SWARM_VECTOR_STORE", raising=False)
    assert isinstance(retrieval.make_vector_store(), retrieval.MemoryVectorStore)


def test_pgvector_falls_back_without_database_url(monkeypatch):
    monkeypatch.setenv("SWARM_VECTOR_STORE", "pgvector")
    monkeypatch.setattr(retrieval.config, "database_url", lambda: "")
    assert isinstance(retrieval.make_vector_store(), retrieval.MemoryVectorStore)


def test_pgvector_falls_back_when_connection_fails(monkeypatch):
    monkeypatch.setenv("SWARM_VECTOR_STORE", "pgvector")
    monkeypatch.setattr(retrieval.config, "database_url", lambda: "postgresql://x/y")

    def boom(self):
        raise RuntimeError("no postgres")

    monkeypatch.setattr(retrieval.PgVectorStore, "_ensure", boom)
    # Unreachable DB must degrade to memory, never crash the run.
    assert isinstance(retrieval.make_vector_store(), retrieval.MemoryVectorStore)


# ── MemoryVectorStore ──────────────────────────────────────────────────────────

def test_pgvector_dsn_strips_sqlalchemy_driver_suffix():
    # persistence shares DATABASE_URL as postgresql+psycopg://…; psycopg.connect
    # needs a raw libpq URI. Without normalisation pgvector dies silently → memory.
    f = retrieval.PgVectorStore._libpq_dsn
    assert f("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert f("postgresql+psycopg2://u:p@h/db") == "postgresql://u:p@h/db"
    assert f("postgresql://u:p@h/db") == "postgresql://u:p@h/db"  # already raw, untouched


def test_memory_store_ranks_by_cosine():
    store = retrieval.MemoryVectorStore()
    store.add([("a.py", 1, "alpha", [1.0, 0.0]), ("b.py", 2, "beta", [0.0, 1.0])])
    hits = store.search([1.0, 0.0], k=2)
    assert hits[0].path == "a.py" and hits[0].start_line == 1


# ── PgVectorStore SQL (fake connection) ──────────────────────────────────────────

def test_pgvector_add_emits_ddl_and_insert():
    conn = _FakeConn()
    store = retrieval.PgVectorStore(dim=3, namespace="ns", conn=conn)
    store.add([("a.py", 1, "code", [0.1, 0.2, 0.3])])
    sqls = [c[0] for c in conn.calls]
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in s for s in sqls)
    assert any("CREATE TABLE IF NOT EXISTS swarm_chunks" in s and "vector(3)" in s for s in sqls)
    assert any("ivfflat" in s and "vector_cosine_ops" in s for s in sqls)
    assert any(s.startswith("DELETE FROM swarm_chunks") for s in sqls)
    ins = [c for c in conn.calls if c[0].startswith("INSERT INTO swarm_chunks")]
    assert ins and ins[0][1] == ("ns", "a.py", 1, "code", "[0.1,0.2,0.3]")
    assert conn.commits >= 1


def test_pgvector_ddl_runs_once():
    conn = _FakeConn()
    store = retrieval.PgVectorStore(dim=2, namespace="ns", conn=conn)
    store.add([("a.py", 1, "x", [1.0, 0.0])])
    store.add([("b.py", 1, "y", [0.0, 1.0])])
    creates = [c for c in conn.calls if c[0].startswith("CREATE TABLE")]
    assert len(creates) == 1  # schema ensured only on the first call


def test_pgvector_search_builds_cosine_query_and_maps_hits():
    conn = _FakeConn(rows=[("auth.py", 5, "def login():\n    pass", 0.92)])
    store = retrieval.PgVectorStore(dim=3, namespace="ns", conn=conn)
    hits = store.search([0.1, 0.2, 0.3], k=3)
    sel = next(c for c in conn.calls if c[0].startswith("SELECT"))
    assert "embedding <=> %s::vector" in sel[0] and "LIMIT %s" in sel[0]
    assert sel[1] == ("[0.1,0.2,0.3]", "ns", "[0.1,0.2,0.3]", 3)
    assert len(hits) == 1 and hits[0].path == "auth.py" and hits[0].start_line == 5
    assert hits[0].score == 0.92


# ── EmbeddingRetriever delegates to whatever store it's given ─────────────────────

def test_embedding_retriever_uses_injected_pgvector_store():
    conn = _FakeConn(rows=[("a.py", 1, "alpha block", 0.99)])

    def embed(texts):
        return [[1.0, 0.0] for _ in texts]

    r = retrieval.EmbeddingRetriever(
        embed_fn=embed, store=retrieval.PgVectorStore(dim=2, conn=conn))
    r.add_chunks("a.py", [(1, "alpha block")])
    assert any(c[0].startswith("INSERT INTO swarm_chunks") for c in conn.calls)
    hits = r.query("alpha")
    assert hits and hits[0].path == "a.py" and hits[0].score == 0.99
