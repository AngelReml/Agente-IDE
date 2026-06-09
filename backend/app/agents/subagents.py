"""
Specialised subagents (researcher, reviewer) — now async and non-blocking.

The model calls run in a worker thread (asyncio.to_thread) so they no longer
freeze the event loop, which lets the orchestrator fan out work in parallel.
"""
import asyncio
import logging

from langchain_core.messages import HumanMessage

from ..smart_router import get_cheap_model, get_heavy_model

logger = logging.getLogger(__name__)


async def _ask(prompt: str) -> str:
    """Invoke the cheap model in a thread; fall back to a heavy model on error."""
    def _call(model_factory):
        model = model_factory()
        return model.invoke([HumanMessage(content=prompt)]).content

    try:
        return await asyncio.to_thread(_call, get_cheap_model)
    except Exception as exc:
        logger.warning("subagent cheap failed: %s — retrying heavy", exc)
        try:
            return await asyncio.to_thread(_call, get_heavy_model)
        except Exception as e:
            return f"Error en subagente: {e}"


async def run_researcher(query: str, project_root: str) -> str:
    from ..tools import get_architecture_tree, grep_search
    structure = get_architecture_tree.invoke({})
    grep_results = grep_search.invoke({"query": query})
    prompt = f"""Actúas como Investigador de Código. Responde a la consulta analizando la estructura.

CONSULTA:
{query}

ESTRUCTURA DEL PROYECTO:
{structure}

RESULTADOS GREP:
{grep_results}

Escribe un reporte estructurado en español:
1. Archivos principales relacionados con la consulta y su rol.
2. Flujo de datos y dependencias clave.
3. Qué archivos deben leerse o modificarse para resolver la consulta."""
    return await _ask(prompt)


async def run_reviewer(file_path: str, diff: str) -> str:
    prompt = f"""Actúas como Ingeniero Principal haciendo Code Review de `{file_path}`.

DIFF:
```diff
{diff}
```

Evalúa con rigor:
1. **Seguridad**: ¿Introduce vulnerabilidades?
2. **Arquitectura**: ¿Respeta el diseño actual?
3. **Rendimiento**: ¿Hay ineficiencias?
4. **Corrección**: ¿Bugs, casos límite no cubiertos?

Veredicto OBLIGATORIO en la primera línea:
- "❌ RECHAZADO: [motivo]" si hay problemas graves.
- "✅ APROBADO: [comentario breve]" si es correcto.
Sé directo y objetivo."""
    return await _ask(prompt)
