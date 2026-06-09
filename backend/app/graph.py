import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, List

from langchain_core.messages import (
    HumanMessage, ToolMessage, BaseMessage, messages_to_dict, messages_from_dict,
)
from langgraph.prebuilt import create_react_agent

from . import smart_router, cost_tracker, state_context, memoria_manager, store, config, runtime, prompts
from .smart_router import RouterState, is_retriable, PROVIDER_COLORS, get_routing_mode, consume_manual_model
from .tools import ALL_TOOLS, ensure_project
from .config import project_root

logger = logging.getLogger(__name__)

# ── Session history (now persisted per-project via store) ───────────────────────

_session_messages: List[BaseMessage] = []


def _trim_tool(msg: ToolMessage) -> ToolMessage:
    name = getattr(msg, "name", "") or ""
    c = msg.content if isinstance(msg.content, str) else str(msg.content)
    if name == "read_file":
        lines = c.count("\n") + 1
        summary = (f"[Archivo leído en turno anterior — {lines} líneas, {len(c):,} chars. "
                   f"Si necesitas el contenido actual vuelve a llamar read_file.]")
        return ToolMessage(content=summary, tool_call_id=msg.tool_call_id, name=name)
    if len(c) > config.MAX_TOOL_CHARS:
        c = c[:config.MAX_TOOL_CHARS] + f"\n…[{len(c)} chars total]"
    return ToolMessage(content=c, tool_call_id=msg.tool_call_id, name=name)


def _load_history() -> None:
    global _session_messages
    try:
        data = store.load_history_raw()
        if data:
            _session_messages = messages_from_dict(data)
            logger.info("Loaded %d messages from session history", len(_session_messages))
    except Exception as e:
        logger.warning("Could not load session history: %s", e)


def _save_history() -> None:
    try:
        store.save_history_raw(messages_to_dict(_session_messages))
    except Exception as e:
        logger.warning("Could not save session history: %s", e)


def clear_session_messages() -> None:
    global _session_messages
    _session_messages = []
    store.clear_history()


def session_message_count() -> int:
    return len(_session_messages)


def _update_session_history(all_messages: list) -> None:
    global _session_messages
    trimmed = [_trim_tool(m) if isinstance(m, ToolMessage) else m for m in all_messages]
    _session_messages = trimmed[-config.MAX_HISTORY:]
    _save_history()


_load_history()

# ── System prompt ────────────────────────────────────────────────────────────────

_BASE_PROMPT = """Eres un equipo de ingenieros senior de software. Ejecutas tareas con código de producción de manera segura, confiable y profesional.

PLANIFICACIÓN (OBLIGATORIO en tareas de 3+ pasos):
- Llama update_plan al inicio con una checklist markdown ('- [ ] paso'). Marca '- [x]' a medida que completas. Vuelve a llamarlo cuando cambie el estado.

MEMORIA DEL PROYECTO:
1. Si no existe `memoria.md`, se inicializa solo. Antes de cambios de alto riesgo (configs, arquitectura, múltiples archivos), LEE `memoria.md`.
2. Cada mutación se registra automáticamente. Actualiza "Decisiones Arquitectónicas" si cambias el diseño general.

SISTEMA DE ARCHIVOS:
- read_file/list_files: lectura de cualquier ruta (los archivos de secretos .env están protegidos).
- write_file/delete_file fuera del workspace: si responde "⚠️ CONFIRMACION REQUERIDA", informa al usuario y vuelve a llamar con overwrite_external=True / confirmed=True.

EDICIÓN — MUY IMPORTANTE:
- edit_file: para modificar un fragmento exacto de UN archivo (preferido).
- apply_patch: para varios cambios o varios archivos a la vez (JSON de {path, old_string, new_string}); valida todo antes de escribir nada (atómico).
- write_file: SOLO para archivos nuevos o reescrituras completas deliberadas.
- En archivos de 200+ líneas, usa edit_file/apply_patch, nunca write_file completo.

VERIFICACIÓN:
- Tras editar, ejecuta run_tests (o run_command con pytest/npm test) antes de git_commit.
- delegate_review para revisar cambios sensibles antes de escribir.

INTERNET:
- fetch_url(url, as_json=True): GET nativo para APIs públicas. Las IP privadas están bloqueadas.

COMANDOS:
- run_command admite python, pip, node, npm/pnpm/yarn, npx, git, curl, pytest, ruff, tsc, mkdir, ls.
- Para tareas complejas de archivos, escribe un script Python y ejecútalo.

FLUJO ESTÁNDAR:
update_plan → get_semantic_map → list_files → read_file → edit_file/apply_patch → run_tests → git_commit.

REGLAS:
- No preguntes salvo confirmaciones externas críticas.
- Fallo de comando → lee el error completo, corrige, máx 3 reintentos.
- Código de producción real, no demos."""


def _base_prompt() -> str:
    # Externalised, versioned prompt (Q3); falls back to the inline constant.
    return prompts.load("system") or _BASE_PROMPT


def _build_system_prompt() -> str:
    base = _base_prompt()
    try:
        snippet = memoria_manager.get_last_changelog_lines(project_root(), n=15)
        if snippet:
            return base + f"\n\n## 📝 BITÁCORA RECIENTE:\n{snippet}"
    except Exception:
        pass
    return base


def _check_state_guard() -> str | None:
    modified = state_context.get_modified_files()
    if not modified:
        return None
    if not state_context.was_changelog_added():
        files_list = ", ".join(list(modified)[:5])
        return (f"⚠️ State Guard: {len(modified)} archivo(s) modificado(s) ({files_list}) "
                f"sin actualizar memoria.md.")
    return None


# ── Streaming agent ───────────────────────────────────────────────────────────────

async def run_swarm_stream(task: str, session_id: str = "default") -> AsyncGenerator[Dict[str, Any], None]:
    ensure_project()
    state_context.reset_session()

    ctx = runtime.new_run(task, session_id)
    store.start_run(ctx.run_id, session_id, task)

    if not smart_router.available_indices():
        yield {"type": "error", "content": "❌ No hay claves API configuradas en .env"}
        yield {"type": "done", "content": ""}
        store.finish_run(ctx.run_id, "error", None, None, ctx.cost.stats())
        return

    state = RouterState(mode=get_routing_mode(), start_model_id=consume_manual_model())

    hist = list(_session_messages)
    if hist:
        yield {"type": "context", "content": f"📎 Contexto activo: {len(hist)} mensajes de sesión anterior"}
    input_messages = hist + [HumanMessage(content=task)]

    captured_messages: list | None = None
    yield {"type": "run", "run_id": ctx.run_id, "content": ""}

    while True:
        entry = state.current()
        if entry is None:
            yield {"type": "error", "content": "❌ Todos los modelos disponibles agotados"}
            yield {"type": "done", "content": ""}
            store.finish_run(ctx.run_id, "exhausted", ctx.provider, ctx.model, ctx.cost.stats())
            return

        info = entry.info()
        ctx.provider, ctx.model = info["provider"], info["model"]
        ctx.loop.reset()

        yield {"type": "info", "content": f"Usando {info['display']}", "model": info["model"],
               "provider": info["provider"], "color": info["color"], "is_free": info["is_free"]}

        try:
            agent = create_react_agent(model=entry.build(), tools=ALL_TOOLS, prompt=_build_system_prompt())
            loop_abort = False

            async for event in agent.astream_events(
                {"messages": input_messages}, version="v2",
                config={"recursion_limit": config.RECURSION_LIMIT},
            ):
                etype = event.get("event", "")
                data = event.get("data", {})
                name = event.get("name", "")

                if etype == "on_chat_model_end":
                    try:
                        usage = data.get("output").usage_metadata  # type: ignore[union-attr]
                        if usage:
                            inp = usage.get("input_tokens", 0)
                            out = usage.get("output_tokens", 0)
                            cost = cost_tracker.record(info["provider"], info["model"], inp, out)
                            ctx.cost.add(inp, out, cost)
                            s = ctx.cost.stats()
                            yield {"type": "cost", **s,
                                   "content": f"🪙 ${s['cost_usd']:.4f} ({s['input_tokens']+s['output_tokens']:,} tokens)"}
                    except Exception:
                        pass

                if etype == "on_tool_start":
                    raw_input = data.get("input", {})
                    repeat = ctx.loop.check(name, raw_input if isinstance(raw_input, dict) else {})
                    if repeat >= config.LOOP_ABORT:
                        loop_abort = True
                        yield {"type": "error", "content": f"🔄 Loop detectado: '{name}' repetido {repeat}× con los mismos args. Abortando."}
                        break
                    if repeat >= config.LOOP_WARN:
                        yield {"type": "info", "content": f"⚠️ Posible loop: '{name}' repetido {repeat}× en la ventana reciente"}

                if etype == "on_chain_end" and name == "LangGraph":
                    try:
                        captured_messages = data["output"]["messages"]
                    except Exception:
                        pass

                parsed = _parse_event(event, info)
                if parsed:
                    if parsed["type"] in ("tool_start", "error"):
                        store.record_event(ctx.run_id, parsed["type"], parsed.get("content", ""), parsed.get("tool"))
                    yield parsed

            if loop_abort:
                yield {"type": "done", "content": "⚠️ Detenido por loop", "provider": info["provider"]}
                store.finish_run(ctx.run_id, "loop", ctx.provider, ctx.model, ctx.cost.stats())
                return

            if captured_messages is not None:
                _update_session_history(captured_messages)

            guard = _check_state_guard()
            if guard:
                yield {"type": "info", "content": guard}

            s = ctx.cost.stats()
            cost_tracker.set_last_run(s)
            if s["input_tokens"] > 0:
                yield {"type": "cost", **s,
                       "content": f"💰 Total run: ${s['cost_usd']:.4f} — {s['input_tokens']:,} in / {s['output_tokens']:,} out"}

            yield {"type": "done", "content": "✅ Completado", "provider": info["provider"]}
            store.finish_run(ctx.run_id, "done", ctx.provider, ctx.model, s)
            return

        except asyncio.CancelledError:
            yield {"type": "info", "content": "⏹ Detenido"}
            store.finish_run(ctx.run_id, "cancelled", ctx.provider, ctx.model, ctx.cost.stats())
            return

        except Exception as exc:
            logger.error("Agent error [%s/%s]: %s", info["provider"], info["model"], exc)
            nxt = state.advance()
            if nxt is None:
                yield {"type": "error", "content": f"❌ {_short(exc)} — sin más modelos"}
                yield {"type": "done", "content": ""}
                store.finish_run(ctx.run_id, "error", ctx.provider, ctx.model, ctx.cost.stats())
                return
            verb = "sin créditos" if is_retriable(exc) else "error"
            yield {"type": "model_switch",
                   "content": f"⚡ {info['display']} {verb} → {nxt.display_name}",
                   "old_model": info["model"], "new_model": nxt.model_id,
                   "provider": nxt.provider, "color": PROVIDER_COLORS.get(nxt.provider, "#6B7280")}
            await asyncio.sleep(0.2)


# ── Event parsing ─────────────────────────────────────────────────────────────────

def _parse_event(event: dict, model_info: dict) -> dict | None:
    etype = event.get("event", "")
    data = event.get("data", {})
    name = event.get("name", "")

    if etype == "on_chat_model_stream":
        chunk = data.get("chunk")
        if not chunk:
            return None
        content = chunk.content if hasattr(chunk, "content") else ""
        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if not content:
            return None
        return {"type": "token", "content": content}

    if etype == "on_tool_start":
        return {"type": "tool_start", "tool": name, "content": _tool_preview(name, data.get("input", {}))}

    if etype == "on_tool_end":
        output = str(data.get("output", ""))
        if len(output) > 400:
            output = output[:400] + "…"
        return {"type": "tool_end", "tool": name, "content": output}

    if etype == "on_chain_end" and name == "LangGraph":
        final = _extract_final(data)
        if final:
            return {"type": "final", "content": final}
    return None


def _tool_preview(tool_name: str, inp: dict) -> str:
    if not isinstance(inp, dict):
        return str(inp)[:80]
    if tool_name == "fetch_url":
        url = inp.get("url", "")
        return url[:77] + "…" if len(url) > 80 else url
    if tool_name == "edit_file":
        p = inp.get("path", "")
        old = inp.get("old_string", "")[:50].replace("\n", "↵")
        new = inp.get("new_string", "")[:50].replace("\n", "↵")
        return f"{p}  «{old}» → «{new}»"
    if tool_name == "apply_patch":
        return f"{inp.get('patch', '')[:80]}…"
    if tool_name in ("read_file", "write_file", "delete_file"):
        p = inp.get("path", "")
        if tool_name == "write_file":
            return f"{p} ({len(inp.get('content', '')):,} chars)"
        return p
    if tool_name in ("run_command", "run_tests"):
        cmd = inp.get("command", inp.get("target", ""))
        return cmd[:90] + ("…" if len(cmd) > 90 else "")
    if tool_name == "git_commit":
        return inp.get("message", "")
    if tool_name == "update_plan":
        return inp.get("plan", "")[:80]
    return str(inp)[:80]


def _extract_final(data: dict) -> str:
    try:
        msgs = data.get("output", {}).get("messages", [])
        if msgs:
            c = getattr(msgs[-1], "content", "")
            if isinstance(c, list):
                c = "".join(b.get("text", "") for b in c if isinstance(b, dict))
            return c or ""
    except Exception:
        pass
    return ""


def _short(exc: Exception) -> str:
    return str(exc)[:200]


# ── Shared cost accounting (used by the swarm orchestrator too) ─────────────────
# Before this, only run_swarm_stream recorded token usage, so swarm subagents and
# the planner were billed at $0. These helpers let any caller record usage.

def _record_usage(usage, model_info: dict) -> dict | None:
    if not usage:
        return None
    try:
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        if inp == 0 and out == 0:
            return None
        cost = cost_tracker.record(model_info.get("provider", ""), model_info.get("model", ""), inp, out)
        s = cost_tracker.session_stats()
        return {"type": "cost", "input_tokens": s["input_tokens"],
                "output_tokens": s["output_tokens"], "cost_usd": s["cost_usd"],
                "content": f"🪙 +${cost:.4f} → ${s['cost_usd']:.4f} acumulado"}
    except Exception:
        return None


def record_cost_from_event(event: dict, model_info: dict) -> dict | None:
    """Record token usage from a LangChain `on_chat_model_end` event. Returns a
    'cost' event dict (or None). Safe to call on every streamed event."""
    if event.get("event") != "on_chat_model_end":
        return None
    output = event.get("data", {}).get("output")
    return _record_usage(getattr(output, "usage_metadata", None), model_info)


def record_cost_from_message(message, model_info: dict) -> dict | None:
    """Record token usage from a single invoke() result message."""
    return _record_usage(getattr(message, "usage_metadata", None), model_info)
