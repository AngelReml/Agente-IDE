"""Phase 3 (architecture plan): Retriever interface + AST symbol chunking.
The default backend (TF-IDF) and its results must not change."""


def test_symbol_chunks_splits_by_function():
    from app import retrieval
    code = "import os\n\ndef alpha():\n    return 1\n\ndef beta():\n    return 2\n"
    chunks = retrieval.symbol_chunks(code, ".py")
    texts = [t for _, t in chunks]
    assert any("import os" in t for t in texts)                       # leading import block
    assert any("def alpha" in t and "def beta" not in t for t in texts)  # one chunk per symbol
    assert any("def beta" in t for t in texts)


def test_symbol_chunks_fallback_for_unknown_ext():
    from app import retrieval
    chunks = retrieval.symbol_chunks("line a\nline b\nline c\n", ".txt")
    assert len(chunks) == 1  # no symbols → single fixed window


def test_retrieval_backend_defaults_to_tfidf(monkeypatch):
    monkeypatch.delenv("SWARM_RETRIEVAL", raising=False)
    from app import config, retrieval
    assert config.retrieval_backend() == "tfidf"
    assert isinstance(retrieval.make_retriever(), retrieval.TfidfRetriever)


def test_embeddings_flag_falls_back_without_key(monkeypatch):
    monkeypatch.setenv("SWARM_RETRIEVAL", "embeddings")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app import retrieval
    # No embedding key → fall back to TF-IDF rather than crash.
    assert isinstance(retrieval.make_retriever(), retrieval.TfidfRetriever)


def test_symbol_chunked_retriever_still_ranks():
    from app import retrieval
    r = retrieval.make_retriever()
    r.add_chunks("auth.py", retrieval.symbol_chunks(
        "def login(user, password):\n    return verify_password(user, password)\n", ".py"))
    r.add_chunks("math.py", retrieval.symbol_chunks(
        "def add(a, b):\n    return a + b\n", ".py"))
    hits = r.query("password login", k=2)
    assert hits and hits[0].path == "auth.py"
