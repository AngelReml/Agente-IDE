"""Phase 1 (architecture plan): per-session isolation of routing, pinned model
and cost — concurrent sessions must not clobber each other."""


def test_per_session_routing_isolation():
    from app import runtime
    a = runtime.SESSIONS.get("iso-A")
    b = runtime.SESSIONS.get("iso-B")
    a.routing_mode = "power"
    b.routing_mode = "fast"
    # Each session keeps its own mode; one does not leak into the other.
    assert runtime.SESSIONS.get("iso-A").routing_mode == "power"
    assert runtime.SESSIONS.get("iso-B").routing_mode == "fast"


def test_session_defaults_to_global_inheritance():
    from app import runtime
    s = runtime.SESSIONS.get("iso-fresh")
    # A brand-new session has no explicit mode → inherits the global default.
    assert s.routing_mode is None


def test_session_manual_model_is_one_shot():
    from app import runtime
    s = runtime.SESSIONS.get("iso-pin")
    s.manual_model = "claude-opus-4-5"
    assert s.consume_manual_model() == "claude-opus-4-5"
    assert s.consume_manual_model() is None  # consumed once, like the global


def test_store_session_cost_aggregates(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from app import store
    store.init()
    store.start_run("r1", "scost", "t")
    store.finish_run("r1", "done", "groq", "m", {"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01})
    store.start_run("r2", "scost", "t")
    store.finish_run("r2", "done", "groq", "m", {"input_tokens": 50, "output_tokens": 10, "cost_usd": 0.02})
    c = store.session_cost("scost")
    assert c["input_tokens"] == 150
    assert c["output_tokens"] == 30
    assert round(c["cost_usd"], 2) == 0.03
