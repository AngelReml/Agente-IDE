"""
Provider chain with priority routing and *complete* fallback.

Key fix vs v3: routing state is no longer a single monotonic module-level index
that could only move forward (which silently disabled the power models as a
fallback in fast mode). Each run owns a RouterState whose candidate list contains
EVERY available model in priority order, so advance() can always reach all of
them. The module keeps a thin default state for the stateless info endpoints.
"""
import asyncio
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROVIDER_COLORS = {
    "anthropic": "#CC785C",
    "openai":    "#10A37F",
    "groq":      "#F55036",
    "glm":       "#2563EB",
    "gemini":    "#4285F4",
    "deepseek":  "#4D6BFE",
    "huggingface": "#FFD21E",
    "openrouter":"#7C3AED",
}

_RETRIABLE = frozenset([
    "429", "402", "500", "502", "503", "529",
    "rate_limit_error", "rate limit exceeded", "rate_limit",
    "insufficient_quota", "quota exceeded", "credit balance", "billing_hard_limit",
    "context_length_exceeded", "maximum context length",
    "model_not_found", "model not found",
    "insufficient balance", "no available balance",
    "overloaded", "overloaded_error", "service unavailable", "timeout", "timed out",
    "1113", "1211",
    "no endpoints found", "provider returned error",
])


def is_retriable(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in _RETRIABLE)


@dataclass
class ModelEntry:
    provider: str
    model_id: str
    display_name: str
    key_env: str
    is_free: bool = False

    def available(self) -> bool:
        return bool(os.getenv(self.key_env))

    def build(self):
        common = dict(max_tokens=8192, temperature=0.4)
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=self.model_id, api_key=os.getenv("ANTHROPIC_API_KEY"),
                                 max_tokens=8192, temperature=0.4)
        from langchain_openai import ChatOpenAI
        base_urls = {
            "groq":        "https://api.groq.com/openai/v1",
            "glm":         "https://open.bigmodel.cn/api/paas/v4/",
            "gemini":      "https://generativelanguage.googleapis.com/v1beta/openai/",
            "deepseek":    "https://api.deepseek.com/v1",
            "huggingface": "https://router.huggingface.co/v1",
            "openrouter":  "https://openrouter.ai/api/v1",
        }
        kwargs = dict(model=self.model_id, api_key=os.getenv(self.key_env), **common)
        if "reasoner" in self.model_id.lower() or self.model_id.lower().startswith(("o1", "o3")):
            # Reasoning models reject a custom temperature (some return HTTP 400).
            kwargs.pop("temperature", None)
        if self.provider == "groq":
            kwargs["max_tokens"] = 8192
        # Allow overriding any provider's endpoint via env, e.g. SWARM_GLM_BASE_URL
        # to point GLM at the international host (https://api.z.ai/api/paas/v4/).
        env_base = os.getenv(f"SWARM_{self.provider.upper()}_BASE_URL")
        if env_base:
            kwargs["base_url"] = env_base
        elif self.provider in base_urls:
            kwargs["base_url"] = base_urls[self.provider]
        if self.provider == "openrouter":
            kwargs["default_headers"] = {
                "HTTP-Referer": "http://localhost:3000", "X-Title": "Swarm IDE",
            }
        return ChatOpenAI(**kwargs)

    def info(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model_id,
            "display": self.display_name,
            "is_free": self.is_free,
            "color": PROVIDER_COLORS.get(self.provider, "#6B7280"),
        }


# ── Priority chain ──────────────────────────────────────────────────────────────
CHAIN: list[ModelEntry] = [
    ModelEntry("anthropic", "claude-opus-4-5",   "Claude Opus 4.5",   "ANTHROPIC_API_KEY"),
    ModelEntry("anthropic", "claude-sonnet-4-5", "Claude Sonnet 4.5", "ANTHROPIC_API_KEY"),
    ModelEntry("anthropic", "claude-haiku-4-5",  "Claude Haiku 4.5",  "ANTHROPIC_API_KEY"),
    ModelEntry("openai", "gpt-4o",      "GPT-4o",      "OPENAI_API_KEY"),
    ModelEntry("openai", "gpt-4o-mini", "GPT-4o Mini", "OPENAI_API_KEY"),
    ModelEntry("groq", "llama-3.3-70b-versatile", "Llama 3.3 70B", "GROQ_API_KEY"),
    ModelEntry("groq", "llama-3.1-8b-instant",    "Llama 3.1 8B",  "GROQ_API_KEY"),
    ModelEntry("glm", "glm-4-plus",  "GLM-4 Plus",  "GLM_API_KEY"),
    ModelEntry("glm", "glm-4-air",   "GLM-4 Air",   "GLM_API_KEY"),
    ModelEntry("glm", "glm-4-flash", "GLM-4 Flash", "GLM_API_KEY"),
    ModelEntry("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", "GEMINI_API_KEY"),
    ModelEntry("gemini", "gemini-2.5-pro",   "Gemini 2.5 Pro",   "GEMINI_API_KEY"),
    ModelEntry("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash", "GEMINI_API_KEY"),
    ModelEntry("deepseek", "deepseek-chat",     "DeepSeek V3", "DEEPSEEK_API_KEY"),
    ModelEntry("deepseek", "deepseek-reasoner", "DeepSeek R1", "DEEPSEEK_API_KEY"),
    ModelEntry("huggingface", "Qwen/Qwen2.5-Coder-32B-Instruct", "Qwen2.5 Coder 32B", "HF_TOKEN"),
    ModelEntry("huggingface", "Qwen/Qwen2.5-72B-Instruct",       "Qwen2.5 72B",       "HF_TOKEN"),
    ModelEntry("huggingface", "meta-llama/Llama-3.3-70B-Instruct","Llama 3.3 70B HF",  "HF_TOKEN"),
    ModelEntry("openrouter", "anthropic/claude-sonnet-4-5", "Claude Sonnet [OR]",  "OPENROUTER_API_KEY"),
    ModelEntry("openrouter", "google/gemini-2.5-pro",       "Gemini 2.5 Pro [OR]", "OPENROUTER_API_KEY"),
    ModelEntry("openrouter", "qwen/qwen3-235b-a22b",        "Qwen3 235B [OR]",     "OPENROUTER_API_KEY"),
    ModelEntry("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 Free",   "OPENROUTER_API_KEY", is_free=True),
    ModelEntry("openrouter", "meta-llama/llama-3.2-3b-instruct:free",  "Llama 3.2 3B Free","OPENROUTER_API_KEY", is_free=True),
    ModelEntry("openrouter", "google/gemma-3-4b-it:free",             "Gemma 3 4B Free",  "OPENROUTER_API_KEY", is_free=True),
]

POWER_PROVIDERS = ["anthropic", "openai", "gemini"]
CHEAP_PROVIDERS = ["groq", "deepseek", "glm", "huggingface"]


def available_indices() -> list[int]:
    return [i for i, e in enumerate(CHAIN) if e.available()]


def model_available(model_id: str) -> bool:
    """True if `model_id` is a known model whose API key is present."""
    return any(e.model_id == model_id and e.available() for e in CHAIN)


def build_order(mode: str) -> list[int]:
    """Full priority-ordered list of available model indices.

    Every available model appears exactly once, so a RouterState built from this
    can fall through to ALL of them — the bug that disabled power models as a
    fast-mode fallback is gone.
    """
    avail = available_indices()

    def group(providers, free=None):
        out = []
        for prov in providers:
            for i in avail:
                e = CHAIN[i]
                if e.provider == prov and (free is None or e.is_free == free):
                    out.append(i)
        return out

    if mode == "power":
        primary, secondary = group(POWER_PROVIDERS), group(CHEAP_PROVIDERS)
    else:
        primary, secondary = group(CHEAP_PROVIDERS), group(POWER_PROVIDERS)

    or_paid = [i for i in avail if CHAIN[i].provider == "openrouter" and not CHAIN[i].is_free]
    or_free = [i for i in avail if CHAIN[i].provider == "openrouter" and CHAIN[i].is_free]

    order: list[int] = []
    for i in primary + secondary + or_paid + or_free + avail:
        if i not in order:
            order.append(i)
    return order


# ── Per-run router state ────────────────────────────────────────────────────────

class RouterState:
    """Owns a run's position in the priority order. Not shared between runs."""

    def __init__(self, mode: str = "fast", start_model_id: str | None = None):
        self.mode = mode if mode in ("fast", "power") else "fast"
        self.order = build_order(self.mode)
        self.ptr = 0
        self.manual = False
        if start_model_id:
            self.set_model(start_model_id)

    def current(self) -> ModelEntry | None:
        if not self.order or self.ptr >= len(self.order):
            return None
        return CHAIN[self.order[self.ptr]]

    def info(self) -> dict:
        e = self.current()
        return e.info() if e else {"provider": None, "model": None, "display": "—",
                                    "is_free": False, "color": "#6B7280"}

    def build_model(self):
        e = self.current()
        if e is None:
            raise RuntimeError("No hay modelos disponibles")
        return e.build()

    def advance(self) -> ModelEntry | None:
        if self.ptr + 1 >= len(self.order):
            return None
        self.ptr += 1
        e = self.current()
        if e:
            logger.warning("Model switch → %s/%s", e.provider, e.model_id)
        return e

    def set_model(self, model_id: str) -> bool:
        for pos, idx in enumerate(self.order):
            if CHAIN[idx].model_id == model_id and CHAIN[idx].available():
                self.ptr = pos
                self.manual = True
                return True
        return False

    def remaining(self) -> int:
        return max(0, len(self.order) - self.ptr - 1)


# ── Default state for the stateless info/admin endpoints ────────────────────────

_routing_mode: str = "fast"
_manual_model_id: str | None = None
_lock = asyncio.Lock()


def set_routing_mode(mode: str) -> str:
    global _routing_mode
    if mode not in ("fast", "power"):
        raise ValueError(f"Modo desconocido: {mode}. Usa 'fast' o 'power'.")
    _routing_mode = mode
    logger.info("Routing mode → %s", mode)
    return mode


def get_routing_mode() -> str:
    return _routing_mode


def _default_state() -> RouterState:
    return RouterState(mode=_routing_mode, start_model_id=_manual_model_id)


def current_info() -> dict:
    return _default_state().info()


async def set_model(model_id: str) -> bool:
    """Pin a model for the next run (consumed once)."""
    global _manual_model_id
    async with _lock:
        for e in CHAIN:
            if e.model_id == model_id and e.available():
                _manual_model_id = model_id
                logger.info("Model manually set → %s/%s", e.provider, e.model_id)
                return True
    return False


def consume_manual_model() -> str | None:
    global _manual_model_id
    mid = _manual_model_id
    _manual_model_id = None
    return mid


def reset() -> None:
    global _manual_model_id
    _manual_model_id = None


def all_info() -> list[dict]:
    return [{**e.info(), "available": e.available()} for e in CHAIN]


# ── Helper models for subagents / diff summary (cheap & heavy) ──────────────────

def get_cheap_model():
    order = ["groq", "deepseek", "glm", "huggingface"]
    for prov in order:
        for e in CHAIN:
            if e.provider == prov and e.available():
                return e.build()
    for e in CHAIN:
        if e.provider == "openrouter" and e.is_free and e.available():
            return e.build()
    for e in CHAIN:
        if e.available():
            return e.build()
    raise RuntimeError("No hay modelos disponibles para routing económico")


def get_heavy_model():
    for prov in POWER_PROVIDERS:
        for e in CHAIN:
            if e.provider == prov and e.available():
                return e.build()
    return get_cheap_model()
