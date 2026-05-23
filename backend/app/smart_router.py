"""
Provider chain: Anthropic → OpenAI → Groq → OpenRouter (free models last resort)
Skips providers whose API keys are absent.
Never stops — always has a next model to try.
"""
import os
import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

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

# Substrings that mean "this provider can't serve us right now" — advance to next model
_RETRIABLE = frozenset([
    # HTTP status codes
    "429",                   # rate limit (universal)
    "402",                   # payment required (DeepSeek, etc.)
    # OpenAI / generic
    "rate_limit_error",
    "rate limit exceeded",
    "insufficient_quota",
    "quota exceeded",
    "credit balance",
    "billing_hard_limit",
    "context_length_exceeded",
    "maximum context length",
    "model_not_found",
    "model not found",
    # Billing strings (DeepSeek, GLM)
    "insufficient balance",
    "no available balance",
    # ZhipuAI-specific error codes
    "1113",                  # 余额不足 — insufficient balance
    "1211",                  # 无效的请求参数 — invalid params / deprecated model
    # OpenRouter
    "no endpoints found",
    "provider returned error",
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
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=self.model_id,
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                api_key=os.getenv("OPENAI_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "groq":
            from langchain_groq import ChatGroq
            return ChatGroq(
                model=self.model_id,
                api_key=os.getenv("GROQ_API_KEY"),
                max_tokens=32768,
                temperature=0.5,
            )
        if self.provider == "glm":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                base_url="https://open.bigmodel.cn/api/paas/v4/",
                api_key=os.getenv("GLM_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "gemini":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.getenv("GEMINI_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "deepseek":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                base_url="https://api.deepseek.com/v1",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "huggingface":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                base_url="https://router.huggingface.co/v1",
                api_key=os.getenv("HF_TOKEN"),
                max_tokens=8192,
                temperature=0.5,
            )
        if self.provider == "openrouter":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_id,
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY"),
                max_tokens=8192,
                temperature=0.5,
                default_headers={
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Swarm IDE",
                },
            )
        raise ValueError(f"Unknown provider: {self.provider}")

    def info(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model_id,
            "display": self.display_name,
            "is_free": self.is_free,
            "color": PROVIDER_COLORS.get(self.provider, "#6B7280"),
        }


# ── Priority chain ────────────────────────────────────────────────────────────
CHAIN: List[ModelEntry] = [
    # 1. Anthropic — best tool use, most reliable
    ModelEntry("anthropic", "claude-opus-4-5",   "Claude Opus 4.5",   "ANTHROPIC_API_KEY"),
    ModelEntry("anthropic", "claude-sonnet-4-5", "Claude Sonnet 4.5", "ANTHROPIC_API_KEY"),
    ModelEntry("anthropic", "claude-haiku-4-5",  "Claude Haiku 4.5",  "ANTHROPIC_API_KEY"),
    # 2. OpenAI — strong coding capability
    ModelEntry("openai", "gpt-4o",      "GPT-4o",      "OPENAI_API_KEY"),
    ModelEntry("openai", "gpt-4o-mini", "GPT-4o Mini", "OPENAI_API_KEY"),
    # 3. Groq — fast cheap inference
    ModelEntry("groq", "llama-3.3-70b-versatile", "Llama 3.3 70B",  "GROQ_API_KEY"),
    ModelEntry("groq", "llama-3.1-8b-instant",    "Llama 3.1 8B",   "GROQ_API_KEY"),  # 70b decommissioned
    # 4. GLM (ZhipuAI) — strong coding, competitive pricing
    ModelEntry("glm", "glm-4-plus",  "GLM-4 Plus",  "GLM_API_KEY"),
    ModelEntry("glm", "glm-4-air",   "GLM-4 Air",   "GLM_API_KEY"),
    ModelEntry("glm", "glm-4-flash", "GLM-4 Flash", "GLM_API_KEY"),
    # 5. Gemini (Google) — strong multimodal reasoning (2.5-flash free tier confirmed working)
    ModelEntry("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", "GEMINI_API_KEY"),
    ModelEntry("gemini", "gemini-2.5-pro",   "Gemini 2.5 Pro",   "GEMINI_API_KEY"),
    ModelEntry("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash", "GEMINI_API_KEY"),
    # 6. DeepSeek — excellent coding, very cheap
    ModelEntry("deepseek", "deepseek-chat",     "DeepSeek V3",  "DEEPSEEK_API_KEY"),
    ModelEntry("deepseek", "deepseek-reasoner", "DeepSeek R1",  "DEEPSEEK_API_KEY"),
    # 7. HuggingFace — cientos de modelos open-source, enrutamiento automático
    ModelEntry("huggingface", "Qwen/Qwen2.5-Coder-32B-Instruct", "Qwen2.5 Coder 32B", "HF_TOKEN"),
    ModelEntry("huggingface", "Qwen/Qwen2.5-72B-Instruct",       "Qwen2.5 72B",       "HF_TOKEN"),
    ModelEntry("huggingface", "meta-llama/Llama-3.3-70B-Instruct","Llama 3.3 70B HF",  "HF_TOKEN"),
    # 8. OpenRouter — paid
    ModelEntry("openrouter", "anthropic/claude-sonnet-4-5",   "Claude Sonnet [OR]", "OPENROUTER_API_KEY"),
    ModelEntry("openrouter", "google/gemini-2.5-pro",         "Gemini 2.5 Pro [OR]","OPENROUTER_API_KEY"),
    ModelEntry("openrouter", "qwen/qwen3-235b-a22b",          "Qwen3 235B [OR]",    "OPENROUTER_API_KEY"),
    # 8. OpenRouter — free (last resort, confirmed working)
    ModelEntry("openrouter", "meta-llama/llama-3.3-70b-instruct:free",  "Llama 3.3 Free",   "OPENROUTER_API_KEY", is_free=True),
    ModelEntry("openrouter", "meta-llama/llama-3.2-3b-instruct:free",   "Llama 3.2 3B Free","OPENROUTER_API_KEY", is_free=True),
    ModelEntry("openrouter", "google/gemma-3-4b-it:free",               "Gemma 3 4B Free",  "OPENROUTER_API_KEY", is_free=True),
]

# Thread-safe global state
_lock = asyncio.Lock()
_idx: int = 0
_manually_set: bool = False  # True when user explicitly picked a model via /api/models/select

# ── Routing mode ──────────────────────────────────────────────────────────────
# "fast"  → empieza en Groq/GLM/DeepSeek (barato, rápido). Ideal para tareas simples.
# "power" → empieza en Anthropic/OpenAI (mejor calidad). Para tareas complejas.
_routing_mode: str = "fast"

_CHEAP_PROVIDERS  = {"groq", "glm", "deepseek", "huggingface"}
_POWER_PROVIDERS  = {"anthropic", "openai", "gemini"}


def set_routing_mode(mode: str) -> str:
    """Set routing mode: 'fast' or 'power'. Returns the new mode."""
    global _routing_mode
    if mode not in ("fast", "power"):
        raise ValueError(f"Unknown mode: {mode}. Use 'fast' or 'power'.")
    _routing_mode = mode
    logger.info("Routing mode → %s", mode)
    return mode


def get_routing_mode() -> str:
    return _routing_mode


def _start_index_for_mode() -> int:
    """Return the chain index to start from based on _routing_mode."""
    avail = _available()
    if not avail:
        return 0

    if _routing_mode == "fast":
        # First non-free cheap model (Groq > DeepSeek > GLM > HuggingFace)
        order = ["groq", "deepseek", "glm", "huggingface"]
        for prov in order:
            for i in avail:
                if CHAIN[i].provider == prov and not CHAIN[i].is_free:
                    return i
        # Fallback: first paid OpenRouter
        for i in avail:
            if CHAIN[i].provider == "openrouter" and not CHAIN[i].is_free:
                return i
        # Last resort: whatever is available first
        return avail[0]

    else:  # "power"
        # Best heavy model (Anthropic > OpenAI > Gemini > rest)
        order = ["anthropic", "openai", "gemini"]
        for prov in order:
            for i in avail:
                if CHAIN[i].provider == prov:
                    return i
        return avail[0]


def _available() -> List[int]:
    return [i for i, e in enumerate(CHAIN) if e.available()]


def current_info() -> dict:
    return CHAIN[_idx].info()


def current_model():
    return CHAIN[_idx].build()


async def advance() -> Optional[ModelEntry]:
    """Advance to the next available model. Returns new entry or None if exhausted."""
    global _idx
    async with _lock:
        avail = _available()
        if not avail:
            return None
        # Find our position among available models
        pos = next((i for i, idx in enumerate(avail) if idx > _idx), None)
        if pos is None:
            return None  # Already at last available
        _idx = avail[pos]
        entry = CHAIN[_idx]
        logger.warning("Model switch → %s/%s", entry.provider, entry.model_id)
        return entry


def reset():
    global _idx
    _idx = 0


def reset_for_run():
    """Reset to the appropriate starting model for a fresh run based on routing mode.
    Skips reset if the user manually selected a model (honours their choice once)."""
    global _idx, _manually_set
    if not _manually_set:
        _idx = _start_index_for_mode()
        entry = CHAIN[_idx]
        logger.info("reset_for_run [%s] → %s/%s", _routing_mode, entry.provider, entry.model_id)
    _manually_set = False  # always consume the flag so next run resets normally


async def set_model(model_id: str) -> bool:
    """Select a specific model by its model_id. Returns True if found and available."""
    global _idx, _manually_set
    async with _lock:
        for i, entry in enumerate(CHAIN):
            if entry.model_id == model_id and entry.available():
                _idx = i
                _manually_set = True
                logger.info("Model manually set → %s/%s", entry.provider, entry.model_id)
                return True
    return False


def all_info() -> List[dict]:
    return [
        {**e.info(), "available": e.available()}
        for e in CHAIN
    ]


# ── Hybrid routing (cheap vs heavy) ──────────────────────────────────────────

_HEAVY_PROVIDERS = {"anthropic", "openai", "gemini"}
_CHEAP_PROVIDERS = {"groq", "glm", "deepseek", "huggingface"}
_FREE_PROVIDERS  = {"openrouter"}


def get_cheap_model():
    """Return the fastest available cheap model (Groq > DeepSeek > GLM > free OpenRouter)."""
    order = ["groq", "deepseek", "glm", "huggingface"]
    for prov in order:
        for entry in CHAIN:
            if entry.provider == prov and entry.available():
                return entry.build()
    # Fallback to free OpenRouter
    for entry in CHAIN:
        if entry.provider == "openrouter" and entry.is_free and entry.available():
            return entry.build()
    # Last resort: whatever is available
    for entry in CHAIN:
        if entry.available():
            return entry.build()
    raise RuntimeError("No models available for cheap routing")


def get_heavy_model():
    """Return the best available heavy model (Anthropic > OpenAI > Gemini)."""
    order = ["anthropic", "openai", "gemini"]
    for prov in order:
        for entry in CHAIN:
            if entry.provider == prov and entry.available():
                return entry.build()
    return current_model()
