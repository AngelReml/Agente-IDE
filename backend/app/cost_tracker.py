"""
Token and cost tracking per run and per session.
Prices are USD per 1M tokens (input, output).
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# ── Pricing table (USD / 1M tokens) ─────────────────────────────────────────

_PRICING: Dict[str, Dict[str, Tuple[float, float]]] = {
    "anthropic": {
        "claude-opus-4-5":   (15.0,  75.0),
        "claude-opus-4-7":   (15.0,  75.0),
        "claude-sonnet-4-5": (3.0,   15.0),
        "claude-sonnet-4-6": (3.0,   15.0),
        "claude-haiku-4-5":  (0.25,  1.25),
    },
    "openai": {
        "gpt-4o":            (2.50,  10.0),
        "gpt-4o-mini":       (0.15,  0.60),
        "o1":                (15.0,  60.0),
        "o1-mini":           (3.0,   12.0),
    },
    "groq": {
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant":    (0.05, 0.08),
        "mixtral-8x7b-32768":      (0.24, 0.24),
    },
    "gemini": {
        "gemini-2.0-flash":  (0.10, 0.40),
        "gemini-1.5-pro":    (1.25, 5.00),
        "gemini-1.5-flash":  (0.075, 0.30),
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
    "huggingface": {},  # free tier — no billing
    "openrouter": {},   # varies; approximate 0 for free models
}


def _price(provider: str, model: str) -> Tuple[float, float]:
    return _PRICING.get(provider, {}).get(model, (0.0, 0.0))


# ── Session-level accumulator ─────────────────────────────────────────────────

@dataclass
class _Stats:
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0

_run:     _Stats = _Stats()
_session: _Stats = _Stats()


def reset_run() -> None:
    global _run
    _run = _Stats()


def record(provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    global _run, _session
    inp_price, out_price = _price(provider, model)
    cost = (input_tokens * inp_price + output_tokens * out_price) / 1_000_000

    _run.input_tokens  += input_tokens
    _run.output_tokens += output_tokens
    _run.cost_usd      += cost

    _session.input_tokens  += input_tokens
    _session.output_tokens += output_tokens
    _session.cost_usd      += cost


def run_stats() -> dict:
    return {
        "input_tokens":  _run.input_tokens,
        "output_tokens": _run.output_tokens,
        "cost_usd":      round(_run.cost_usd, 6),
    }


def session_stats() -> dict:
    return {
        "input_tokens":  _session.input_tokens,
        "output_tokens": _session.output_tokens,
        "cost_usd":      round(_session.cost_usd, 6),
    }
