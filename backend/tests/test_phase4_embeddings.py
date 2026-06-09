"""Phase 4 (architecture plan): EmbeddingRetriever — semantic ranking + a
persistent per-chunk cache. Uses an injected fake embedder (no network, no cost)."""
import re

# A tiny deterministic "embedding": bag-of-words over a fixed vocab so query and
# chunk vectors share dimensionality and cosine is meaningful.
_VOCAB = ["login", "password", "verify", "add", "sum", "number"]


def _fake_embed(texts):
    return [[float(re.findall(r"[a-z]+", t.lower()).count(w)) for w in _VOCAB] for t in texts]


def test_embedding_retriever_ranks_semantically():
    from app import retrieval
    r = retrieval.EmbeddingRetriever(embed_fn=_fake_embed)
    r.add_chunks("auth.py", [(1, "def login(user, password): return verify(password)")])
    r.add_chunks("math.py", [(1, "def add(a, b): return sum")])
    hits = r.query("password login", k=2)
    assert hits and hits[0].path == "auth.py"


def test_embedding_cache_avoids_reembedding(tmp_path):
    from app import retrieval
    calls = {"n": 0}

    def counting_embed(texts):
        calls["n"] += len(texts)
        return [[1.0, 0.0] for _ in texts]

    cache = retrieval._EmbedCache(str(tmp_path))
    retrieval.EmbeddingRetriever(embed_fn=counting_embed, cache=cache).add_chunks(
        "a.py", [(1, "alpha block")])
    first = calls["n"]
    assert first == 1  # one chunk embedded on first build

    # Fresh cache instance reloads from disk → same text served from cache, no new call.
    cache2 = retrieval._EmbedCache(str(tmp_path))
    retrieval.EmbeddingRetriever(embed_fn=counting_embed, cache=cache2).add_chunks(
        "a.py", [(1, "alpha block")])
    assert calls["n"] == first  # no additional embedding calls


def test_embedding_retriever_empty_query_is_safe():
    from app import retrieval
    r = retrieval.EmbeddingRetriever(embed_fn=_fake_embed)
    assert r.query("anything") == []  # nothing indexed → no hits, no crash


def test_make_retriever_uses_embeddings_with_key(monkeypatch):
    monkeypatch.setenv("SWARM_RETRIEVAL", "embeddings")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from app import retrieval
    assert isinstance(retrieval.make_retriever(), retrieval.EmbeddingRetriever)
