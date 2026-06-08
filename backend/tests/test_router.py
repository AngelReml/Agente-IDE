"""Routing / fallback tests — regression guard for the C3 'fast mode never falls
back to power models' bug."""
import importlib


def _reload_router(monkeypatch, keys):
    for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GLM_API_KEY",
              "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "HF_TOKEN", "OPENROUTER_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    for k, v in keys.items():
        monkeypatch.setenv(k, v)
    import app.smart_router as sr
    return importlib.reload(sr)


def test_build_order_fast_starts_cheap(monkeypatch):
    sr = _reload_router(monkeypatch, {"ANTHROPIC_API_KEY": "x", "GROQ_API_KEY": "x"})
    order = sr.build_order("fast")
    first = sr.CHAIN[order[0]]
    assert first.provider == "groq"  # cheap first in fast mode


def test_build_order_power_starts_anthropic(monkeypatch):
    sr = _reload_router(monkeypatch, {"ANTHROPIC_API_KEY": "x", "GROQ_API_KEY": "x"})
    order = sr.build_order("power")
    first = sr.CHAIN[order[0]]
    assert first.provider == "anthropic"


def test_fast_mode_falls_through_to_power(monkeypatch):
    """The core C3 regression: in fast mode, advancing past the cheap models must
    still reach the power models (Anthropic), which the old monotonic index never did."""
    sr = _reload_router(monkeypatch, {"ANTHROPIC_API_KEY": "x", "GROQ_API_KEY": "x"})
    state = sr.RouterState(mode="fast")
    seen = [state.current().provider]
    while True:
        nxt = state.advance()
        if nxt is None:
            break
        seen.append(nxt.provider)
    assert "anthropic" in seen, "power models must be reachable as fallback in fast mode"
    assert "groq" in seen


def test_advance_reaches_every_available_model(monkeypatch):
    sr = _reload_router(monkeypatch, {"ANTHROPIC_API_KEY": "x", "GROQ_API_KEY": "x", "OPENROUTER_API_KEY": "x"})
    avail = len(sr.available_indices())
    state = sr.RouterState(mode="fast")
    count = 1
    while state.advance() is not None:
        count += 1
    assert count == avail


def test_no_keys_means_empty_order(monkeypatch):
    sr = _reload_router(monkeypatch, {})
    assert sr.build_order("fast") == []
    assert sr.RouterState(mode="fast").current() is None
