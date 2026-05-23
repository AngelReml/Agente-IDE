import json
import logging
import asyncio
import hashlib
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List

from langchain_core.messages import (
    HumanMessage, ToolMessage, BaseMessage,
    messages_to_dict, messages_from_dict,
)
from langgraph.prebuilt import create_react_agent

from .smart_router import (
    CHAIN, current_info, current_model, advance, is_retriable, PROVIDER_COLORS, reset_for_run,
)
from .tools import ALL_TOOLS, ensure_project, PROJECT_ROOT
from . import state_context, memoria_manager, cost_tracker

logger = logging.getLogger(__name__)

# ── Session history ────────────────────────────────────────────────────────────

_session_messages: List[BaseMessage] = []
_MAX_HISTORY    = 60
_MAX_TOOL_CHARS = 800

_HISTORY_FILE = Path(PROJECT_ROOT) / ".swarm" / "session_history.json"


def _trim_tool(msg: ToolMessage) -> ToolMessage:
    name = getattr(msg, "name", "") or ""
    c = msg.content if isinstance(msg.content, str) else str(msg.content)

    # read_file results can be huge — replace with a summary note so the next run
    # knows the file was read without burning thousands of tokens on stale content.
    if name == "read_file":
        lines = c.count("\n") + 1
        summary = (
            f"[Archivo leído en turno anterior — {lines} líneas, {len(c):,} chars. "
            f"Si necesitas el contenido actual vuelve a llamar read_file.]"
        )
        return ToolMessage(content=summary, tool_call_id=msg.tool_call_id, name=name)

    if len(c) > _MAX_TOOL_CHARS:
        c = c[:_MAX_TOOL_CHARS] + f"\n…[{len(c)} chars total]"
    return ToolMessage(content=c, tool_call_id=msg.tool_call_id, name=name)


def _save_history() -> None:
    try:
        data = messages_to_dict(_session_messages)
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not save session history: %s", e)


def _load_history() -> None:
    global _session_messages
    try:
        if _HISTORY_FILE.exists():
            data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            _session_messages = messages_from_dict(data)
            logger.info("Loaded %d messages from session history", len(_session_messages))
    except Exception as e:
        logger.warning("Could not load session history: %s", e)


def clear_session_messages() -> None:
    global _session_messages
    _session_messages = []
    try:
        _HISTORY_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def session_message_count() -> int:
    return len(_session_messages)


def _update_session_history(all_messages: list) -> None:
    global _session_messages
    trimmed = [_trim_tool(m) if isinstance(m, ToolMessage) else m for m in all_messages]
    _session_messages = trimmed[-_MAX_HISTORY:]
    _save_history()


# Try loading persisted history on startup
_load_history()

# ── Loop / safety guard ────────────────────────────────────────────────────────

_LOOP_WARN  = 3   # emit warning after N identical consecutive tool calls
_LOOP_ABORT = 6   # abort run after N identical consecutive tool calls

class _LoopDetector:
    def __init__(self):
        self._last_key: str = ""
        self._count: int = 0

    def reset(self):
        self._last_key = ""
        self._count = 0

    def check(self, tool_name: str, tool_input: dict) -> int:
        """Returns current repeat count for this tool+args combo."""
        raw = json.dumps(tool_input, sort_keys=True, default=str)
        key = f"{tool_name}:{hashlib.md5(raw.encode()).hexdigest()[:8]}"
        if key == self._last_key:
            self._count += 1
        else:
            self._last_key = key
            self._count = 1
        return self._count


# ── Base system prompt ─────────────────────────────────────────────────────────

_BASE_PROMPT = """Eres un equipo de ingenieros senior de software. Ejecutas tareas con código de producción de manera segura, confiable y profesional.

NORMATIVA OBLIGATORIA DE BUENAS PRÁCTICAS — MEMORIA DEL PROYECTO:
1. INICIALIZACIÓN: Al iniciar un nuevo proyecto o tarea, verifica si existe el archivo `memoria.md`. Si no existe, inicialízalo.
2. CONSULTA OBLIGATORIA PRE-CAMBIO: Antes de cualquier cambio crítico o de alto riesgo (configs, arquitectura, múltiples archivos): LEE `memoria.md` primero.
3. REGISTRO: Cada mutación se registra automáticamente. Actualiza manualmente "Decisiones Arquitectónicas" si cambias la arquitectura general.

ACCESO AL SISTEMA DE ARCHIVOS:
- read_file y list_files: acceso completo a CUALQUIER ruta del PC.
- write_file y delete_file FUERA del workspace: si devuelve "⚠️ CONFIRMACION REQUERIDA", informa al usuario y llama de nuevo con overwrite_external=True o confirmed=True.

INTERNET Y APIs:
- fetch_url(url): HTTP GET nativo — usa para Open-Meteo, CoinGecko, Wikipedia, etc. SIN necesitar pip install. Soporta JSON. Úsala SIEMPRE como primer intento antes de escribir scripts con requests.
- Ejemplo: fetch_url("https://api.open-meteo.com/v1/forecast?latitude=40.4&longitude=-3.7&current_weather=true", as_json=True)

EJECUCIÓN DE COMANDOS:
- run_command admite: python, pip, node, npm, npx, git, curl, mkdir, ls.
- mkdir NO necesita instalación — está implementado nativamente.
- Para instalar paquetes: run_command("pip install <paquete>") o run_command("python -m pip install <paquete>").
- Para tareas complejas de archivos/directorios: escribe un script Python y ejecútalo. Es más fiable que shell commands.
- Si un script falla por ModuleNotFoundError: lee el error, instala con pip, re-ejecuta.

HERRAMIENTAS SEMÁNTICAS:
- get_semantic_map(): Mapa de símbolos indexado del proyecto.
- search_semantic_symbol(symbol): Localiza función/clase/tipo en el índice.

PROTOCOLO DE EDICIÓN — MUY IMPORTANTE:
- edit_file: USA ESTO para modificar archivos existentes. Solo das old_string + new_string. NUNCA el archivo completo. Eficiente, atómico y seguro contra errores de contexto.
- write_file: SOLO para archivos nuevos o reescrituras completas deliberadas.
- Si el archivo tiene más de 200 líneas, SIEMPRE usa edit_file para modificaciones.

FLUJO ESTÁNDAR:
1. get_semantic_map → entender arquitectura indexada
2. list_files → estructura del directorio
3. read_file → leer el archivo a modificar (necesario para ver el old_string exacto)
4. edit_file → cambio quirúrgico (old_string → new_string)
5. run_command → verificar que compila/pasa tests
6. git_commit → solo cuando compile

REGLAS ABSOLUTAS:
- Nunca preguntes salvo por confirmaciones externas críticas.
- Fallo de comando → lee error completo, corrige, máx 3 reintentos.
- Si edit_file dice "cadena no encontrada": re-lee el archivo, copia old_string con exactitud.
- Código de producción real, no demos."""


def _build_system_prompt() -> str:
    try:
        snippet = memoria_manager.get_last_changelog_lines(PROJECT_ROOT, n=15)
        if snippet:
            return _BASE_PROMPT + f"\n\n## 📝 BITÁCORA RECIENTE (últimas mutaciones del proyecto):\n{snippet}"
    except Exception:
        pass
    return _BASE_PROMPT


# ── State Guard ────────────────────────────────────────────────────────────────

def _check_state_guard() -> str | None:
    modified = state_context.get_modified_files()
    if not modified:
        return None
    if not state_context.was_changelog_added():
        files_list = ", ".join(list(modified)[:5])
        return (
            f"⚠️ State Guard: {len(modified)} archivo(s) modificado(s) ({files_list}) "
            f"sin actualizar memoria.md."
        )
    return None


# ── Streaming agent ────────────────────────────────────────────────────────────

async def run_swarm_stream(task: str) -> AsyncGenerator[Dict[str, Any], None]:
    ensure_project()
    state_context.reset_session()
    reset_for_run()
    cost_tracker.reset_run()

    available = [e for e in CHAIN if e.available()]
    if not available:
        yield {"type": "error", "content": "❌ No hay claves API configuradas en .env"}
        yield {"type": "done",  "content": ""}
        return

    hist = list(_session_messages)
    if hist:
        yield {
            "type": "context",
            "content": f"📎 Contexto activo: {len(hist)} mensajes de sesión anterior",
        }

    input_messages = hist + [HumanMessage(content=task)]

    attempted: set[str] = set()
    captured_messages: list | None = None
    loop_detector = _LoopDetector()

    while True:
        info = current_info()
        model_id = info["model"]

        if model_id in attempted and len(attempted) >= len(available):
            yield {"type": "error", "content": "❌ Todos los modelos agotados"}
            yield {"type": "done",  "content": ""}
            return

        if model_id in attempted:
            entry = await advance()
            if entry is None:
                yield {"type": "error", "content": "❌ Sin más modelos disponibles"}
                yield {"type": "done",  "content": ""}
                return
            info = entry.info()
            model_id = info["model"]

        attempted.add(model_id)
        loop_detector.reset()

        yield {
            "type": "info",
            "content": f"Usando {info['display']}",
            "model": model_id,
            "provider": info["provider"],
            "color": info["color"],
            "is_free": info["is_free"],
        }

        try:
            system_prompt = _build_system_prompt()
            model = current_model()
            agent = create_react_agent(model=model, tools=ALL_TOOLS, prompt=system_prompt)

            loop_abort = False

            async for event in agent.astream_events(
                {"messages": input_messages},
                version="v2",
                config={"recursion_limit": 60},
            ):
                etype = event.get("event", "")
                data  = event.get("data", {})
                name  = event.get("name", "")

                # ── Cost tracking ──────────────────────────────────────────
                if etype == "on_chat_model_end":
                    try:
                        usage = data.get("output").usage_metadata  # type: ignore[union-attr]
                        if usage:
                            inp = usage.get("input_tokens", 0)
                            out = usage.get("output_tokens", 0)
                            cost_tracker.record(info["provider"], model_id, inp, out)
                            stats = cost_tracker.run_stats()
                            yield {
                                "type": "cost",
                                "input_tokens":  stats["input_tokens"],
                                "output_tokens": stats["output_tokens"],
                                "cost_usd":      stats["cost_usd"],
                                "content":       f"🪙 ${stats['cost_usd']:.4f} ({stats['input_tokens']+stats['output_tokens']:,} tokens)",
                            }
                    except Exception:
                        pass

                # ── Loop detection ─────────────────────────────────────────
                if etype == "on_tool_start":
                    raw_input = data.get("input", {})
                    repeat = loop_detector.check(name, raw_input if isinstance(raw_input, dict) else {})
                    if repeat >= _LOOP_ABORT:
                        loop_abort = True
                        yield {
                            "type": "error",
                            "content": f"🔄 Loop detectado: '{name}' llamado {repeat}× con los mismos args. Abortando.",
                        }
                        break
                    if repeat >= _LOOP_WARN:
                        yield {
                            "type": "info",
                            "content": f"⚠️ Posible loop: '{name}' repetido {repeat}× con los mismos args",
                        }

                # Capture final messages
                if etype == "on_chain_end" and name == "LangGraph":
                    try:
                        captured_messages = data["output"]["messages"]
                    except Exception:
                        pass

                parsed = _parse_event(event, info)
                if parsed:
                    yield parsed

            if loop_abort:
                yield {"type": "done", "content": "⚠️ Detenido por loop", "provider": info["provider"]}
                return

            if captured_messages is not None:
                _update_session_history(captured_messages)

            guard_warning = _check_state_guard()
            if guard_warning:
                yield {"type": "info", "content": guard_warning}

            # Final cost summary
            stats = cost_tracker.run_stats()
            if stats["input_tokens"] > 0:
                yield {
                    "type": "cost",
                    "input_tokens":  stats["input_tokens"],
                    "output_tokens": stats["output_tokens"],
                    "cost_usd":      stats["cost_usd"],
                    "content":       f"💰 Total run: ${stats['cost_usd']:.4f} — {stats['input_tokens']:,} in / {stats['output_tokens']:,} out",
                }

            yield {"type": "done", "content": "✅ Completado", "provider": info["provider"]}
            return

        except asyncio.CancelledError:
            yield {"type": "info", "content": "⏹ Detenido"}
            return

        except Exception as exc:
            logger.error("Agent error [%s/%s]: %s", info["provider"], model_id, exc)

            if is_retriable(exc):
                next_entry = await advance()
                if next_entry is None or next_entry.model_id in attempted:
                    yield {"type": "error", "content": f"❌ {_short(exc)} — sin más modelos"}
                    yield {"type": "done",  "content": ""}
                    return
                yield {
                    "type": "model_switch",
                    "content": f"⚡ {info['display']} sin créditos → {next_entry.display_name}",
                    "old_model": model_id,
                    "new_model": next_entry.model_id,
                    "provider":  next_entry.provider,
                    "color":     PROVIDER_COLORS.get(next_entry.provider, "#6B7280"),
                }
                await asyncio.sleep(0.3)
            else:
                yield {"type": "error", "content": f"❌ {_short(exc)}"}
                next_entry = await advance()
                if next_entry is None or next_entry.model_id in attempted:
                    yield {"type": "done", "content": "❌ Sin más modelos disponibles"}
                    return
                yield {
                    "type": "model_switch",
                    "content": f"↩️ Reintentando con {next_entry.display_name}",
                    "new_model": next_entry.model_id,
                    "provider":  next_entry.provider,
                    "color":     PROVIDER_COLORS.get(next_entry.provider, "#6B7280"),
                }


# ── Event parsing ──────────────────────────────────────────────────────────────

def _parse_event(event: dict, model_info: dict) -> dict | None:
    etype = event.get("event", "")
    data  = event.get("data", {})
    name  = event.get("name", "")

    if etype == "on_chat_model_stream":
        chunk = data.get("chunk")
        if not chunk:
            return None
        content = chunk.content if hasattr(chunk, "content") else ""
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if not content:
            return None
        return {"type": "token", "content": content}

    if etype == "on_tool_start":
        raw_input = data.get("input", {})
        preview = _tool_preview(name, raw_input)
        return {"type": "tool_start", "tool": name, "content": preview}

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
    if tool_name == "fetch_url":
        url = inp.get("url", "")
        # Shorten long URLs
        if len(url) > 80:
            url = url[:77] + "…"
        return url
    if tool_name == "edit_file":
        p   = inp.get("path", "")
        old = inp.get("old_string", "")[:50].replace("\n", "↵")
        new = inp.get("new_string", "")[:50].replace("\n", "↵")
        return f"{p}  «{old}» → «{new}»"
    if tool_name in ("read_file", "write_file", "delete_file"):
        p = inp.get("path", "")
        if tool_name == "write_file":
            chars = len(inp.get("content", ""))
            return f"{p} ({chars:,} chars)"
        return p
    if tool_name == "run_command":
        cmd = inp.get("command", "")
        return cmd[:90] + ("…" if len(cmd) > 90 else "")
    if tool_name == "git_commit":
        return inp.get("message", "")
    return str(inp)[:80]


def _extract_final(data: dict) -> str:
    try:
        msgs = data.get("output", {}).get("messages", [])
        if msgs:
            last = msgs[-1]
            c = getattr(last, "content", "")
            if isinstance(c, list):
                c = "".join(b.get("text", "") for b in c if isinstance(b, dict))
            return c or ""
    except Exception:
        pass
    return ""


def _short(exc: Exception) -> str:
    return str(exc)[:200]
