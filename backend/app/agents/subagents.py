import os
import logging
from langchain_core.messages import HumanMessage
from ..smart_router import get_cheap_model, current_model
from .. import safe_fs

logger = logging.getLogger(__name__)


def run_researcher(query: str, project_root: str) -> str:
    """Subagente Investigador — usa el modelo rápido/barato."""
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

    try:
        model = get_cheap_model()
        response = model.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as exc:
        logger.warning("run_researcher cheap failed: %s — retrying with main model", exc)
        try:
            response = current_model().invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            return f"Error en subagente Researcher: {e}"


def run_reviewer(file_path: str, diff: str) -> str:
    """Subagente Revisor — usa el modelo rápido/barato."""
    prompt = f"""Actúas como Ingeniero Principal haciendo Code Review de `{file_path}`.

DIFF:
```diff
{diff}
```

Evalúa:
1. **Seguridad**: ¿Introduce vulnerabilidades?
2. **Arquitectura**: ¿Respeta el diseño actual?
3. **Rendimiento**: ¿Hay ineficiencias?

Veredicto:
- Si hay problemas graves: "❌ RECHAZADO: [motivo]"
- Si es correcto: "✅ APROBADO: [comentario breve]"
Sé directo y objetivo."""

    try:
        model = get_cheap_model()
        response = model.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as exc:
        logger.warning("run_reviewer cheap failed: %s — retrying with main model", exc)
        try:
            response = current_model().invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            return f"Error en subagente Reviewer: {e}"
