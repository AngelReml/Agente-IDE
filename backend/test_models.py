"""
Test rápido de todos los modelos del chain.
Ejecutar desde la carpeta backend: python test_models.py
"""
import os, sys, asyncio, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

TESTS = [
    # (provider, model_id, display, base_url_or_None)
    ("anthropic", "claude-opus-4-5",   "Claude Opus 4.5",   None),
    ("anthropic", "claude-sonnet-4-5", "Claude Sonnet 4.5", None),
    ("anthropic", "claude-haiku-4-5",  "Claude Haiku 4.5",  None),
    ("openai",    "gpt-4o",            "GPT-4o",            None),
    ("openai",    "gpt-4o-mini",       "GPT-4o Mini",       None),
    ("groq",      "llama-3.3-70b-versatile", "Llama 3.3 70B Groq",  None),
    ("groq",      "llama-3.1-8b-instant",    "Llama 3.1 8B Groq",   None),
    ("glm",       "glm-4-plus",        "GLM-4 Plus",        "https://open.bigmodel.cn/api/paas/v4/"),
    ("glm",       "glm-4-air",         "GLM-4 Air",         "https://open.bigmodel.cn/api/paas/v4/"),
    ("glm",       "glm-4-flash",       "GLM-4 Flash",       "https://open.bigmodel.cn/api/paas/v4/"),
    ("gemini",    "gemini-2.5-flash",  "Gemini 2.5 Flash",  "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("gemini",    "gemini-2.5-pro",    "Gemini 2.5 Pro",    "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("gemini",    "gemini-2.0-flash",  "Gemini 2.0 Flash",  "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("deepseek",  "deepseek-chat",     "DeepSeek V3",       "https://api.deepseek.com/v1"),
    ("deepseek",  "deepseek-reasoner", "DeepSeek R1",       "https://api.deepseek.com/v1"),
    ("huggingface","Qwen/Qwen2.5-Coder-32B-Instruct","Qwen2.5 Coder HF","https://router.huggingface.co/v1"),
    ("huggingface","Qwen/Qwen2.5-72B-Instruct",      "Qwen2.5 72B HF",  "https://router.huggingface.co/v1"),
    ("huggingface","meta-llama/Llama-3.3-70B-Instruct","Llama 3.3 HF",  "https://router.huggingface.co/v1"),
    ("openrouter","anthropic/claude-sonnet-4-5",          "Claude Sonnet [OR]",   "https://openrouter.ai/api/v1"),
    ("openrouter","google/gemini-2.5-pro",                "Gemini 2.5 Pro [OR]",  "https://openrouter.ai/api/v1"),
    ("openrouter","qwen/qwen3-235b-a22b",                 "Qwen3 235B [OR]",      "https://openrouter.ai/api/v1"),
    ("openrouter","meta-llama/llama-3.3-70b-instruct:free",  "Llama 3.3 Free [OR]",    "https://openrouter.ai/api/v1"),
    ("openrouter","meta-llama/llama-3.2-3b-instruct:free",  "Llama 3.2 3B Free [OR]", "https://openrouter.ai/api/v1"),
    ("openrouter","google/gemma-3-4b-it:free",               "Gemma 3 4B Free [OR]",   "https://openrouter.ai/api/v1"),
]

KEY_MAP = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "glm":        "GLM_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "huggingface":"HF_TOKEN",
    "openrouter": "OPENROUTER_API_KEY",
}

PROMPT = "Responde solo con la palabra: OK"
MAX_TOK = 50   # enough for any model's minimum, low enough to stay cheap

OK   = "OK  "
FAIL = "FAIL"
SKIP = "----"


def test_anthropic(model_id):
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model_id,
        max_tokens=MAX_TOK,
        messages=[{"role": "user", "content": PROMPT}]
    )
    return msg.content[0].text.strip()


def test_openai_compat(model_id, base_url, api_key, extra_headers=None):
    from openai import OpenAI
    kwargs = dict(api_key=api_key, base_url=base_url) if base_url else dict(api_key=api_key)
    client = OpenAI(**kwargs)
    if extra_headers:
        client.default_headers.update(extra_headers)
    resp = client.chat.completions.create(
        model=model_id,
        max_tokens=MAX_TOK,
        messages=[{"role": "user", "content": PROMPT}]
    )
    msg = resp.choices[0].message
    # Some models (extended thinking, reasoning) return content=None
    content = msg.content
    if not content:
        content = getattr(msg, "reasoning_content", None) or "[empty response]"
    return content.strip()


results = []

for provider, model_id, display, base_url in TESTS:
    key_env = KEY_MAP[provider]
    key = os.getenv(key_env)

    if not key:
        results.append((SKIP, display, "Sin clave API"))
        continue

    t0 = time.time()
    try:
        if provider == "anthropic":
            out = test_anthropic(model_id)
        elif provider == "groq":
            from groq import Groq
            client = Groq(api_key=key)
            resp = client.chat.completions.create(
                model=model_id,
                max_tokens=MAX_TOK,
                messages=[{"role": "user", "content": PROMPT}]
            )
            out = resp.choices[0].message.content.strip()
        elif provider == "openrouter":
            out = test_openai_compat(model_id, base_url, key, {
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "SwarmIDE"
            })
        else:
            out = test_openai_compat(model_id, base_url, key)

        ms = int((time.time() - t0) * 1000)
        results.append((OK, display, f"{out!r}  [{ms}ms]"))

    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        err = str(e)[:120]
        results.append((FAIL, display, err))

# ── Print report ──────────────────────────────────────────────────────────────
print("\n" + "="*72)
print("  SWARM IDE — TEST DE MODELOS")
print("="*72)
last_provider = None
for (prov, model_id, display, _) in TESTS:
    if prov != last_provider:
        print(f"\n  [{prov.upper()}]")
        last_provider = prov
    icon, name, detail = results[TESTS.index((prov, model_id, display, _))]
    detail_safe = detail.encode("ascii", "replace").decode("ascii")
    print(f"    {icon}  {name:<34} {detail_safe}")

ok_count   = sum(1 for r in results if r[0] == OK)
fail_count = sum(1 for r in results if r[0] == FAIL)
skip_count = sum(1 for r in results if r[0] == SKIP)
print(f"\n  Resultado: {ok_count} OK · {fail_count} FALLIDOS · {skip_count} SIN CLAVE")
print("="*72 + "\n")
