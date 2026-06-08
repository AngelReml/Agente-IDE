"""
Token and cost pricing. Prices are USD per 1M tokens (input, output).

The pricing table is now aligned with the actual model chain (the v3 table was
missing gemini-2.5-* — which the chain uses — so Gemini runs were billed at $0).
Per-run accounting moved to runtime.RunCost; this module owns the pricing
function and the cumulative session total.
"""
import logging
from dataclasses import dataclass
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

_PRICING: Dict[str, Dict[str, Tuple[float, float]]] = {
    "anthropic": {
        "claude-opus-4-5":   (15.0, 75.0),
        "claude-sonnet-4-5": (3.0,  15.0),
        "claude-haiku-4-5":  (0.25, 1.25),
    },
    "openai": {
        "gpt-4o":      (2.50, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
    },
    "groq": {
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant":    (0.05, 0.08),
    },
    "gemini": {
        "gemini-2.5-pro":   (1.25, 10.0),
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-2.0-flash": (0.10, 0.40),
    },
    "deepseek": {
        "deepseek-chat":     (0.27, 1.10),
        "deepseek-reasoner": (0.55, 2.19),
    },
    "glm": {
        "glm-4-plus":  (0.70, 0.70),
        "glm-4-air":   (0.14, 0.14),
        "glm-4-flash": (0.01, 0.01),
    },
    "huggingface": {},  # free tier
    "openrouter": {
        "anthropic/claude-sonnet-4-5": (3.0, 15.0),
        "google/gemini-2.5-pro":       (1.25, 10.0),
        "qwen/qwen3-235b-a22b":        (0.20, 0.60),
        # ":free" models → 0
    },
}


def price(provider: str, model: str) -> Tuple[float, float]:
    return _PRICING.get(provider, {}).get(model, (0.0, 0.0))


def cost_of(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = price(provider, model)
    return (input_tokens * inp + output_tokens * out) / 1_000_000


# ── Cumulative session total ─────────────────────────────────────────────────────

@dataclass
class _Stats:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


_session = _Stats()
_last_run = _Stats()


def record(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Add usage to the session total and return the cost of this call."""
    cost = cost_of(provider, model, input_tokens, output_tokens)
    _session.input_tokens += input_tokens
    _session.output_tokens += output_tokens
    _session.cost_usd += cost
    return cost


def set_last_run(stats: dict) -> None:
    _last_run.input_tokens = stats.get("input_tokens", 0)
    _last_run.output_tokens = stats.get("output_tokens", 0)
    _last_run.cost_usd = stats.get("cost_usd", 0.0)


def run_stats() -> dict:
    return {
        "input_tokens": _last_run.input_tokens,
        "output_tokens": _last_run.output_tokens,
        "cost_usd": round(_last_run.cost_usd, 6),
    }


def session_stats() -> dict:
    return {
        "input_tokens": _session.input_tokens,
        "output_tokens": _session.output_tokens,
        "cost_usd": round(_session.cost_usd, 6),
    }
