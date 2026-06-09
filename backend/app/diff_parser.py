"""
Parse unified diffs and generate structured human summaries
using the cheapest available model.
"""
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_diff_stats(diff: str) -> dict[str, int]:
    lines = diff.splitlines()
    added   = sum(1 for ln in lines if ln.startswith('+') and not ln.startswith('+++'))
    removed = sum(1 for ln in lines if ln.startswith('-') and not ln.startswith('---'))
    hunks   = len(re.findall(r'^@@', diff, re.MULTILINE))
    return {"lines_added": added, "lines_removed": removed, "hunks": hunks}


def _fallback_summary(file_path: str, stats: dict[str, int]) -> dict[str, Any]:
    fname = file_path.split("/")[-1].split("\\")[-1]
    risk = "alto" if stats["lines_removed"] > 30 else "medio" if stats["lines_added"] > 15 else "bajo"
    return {
        "resumen_humano": f"Se modificó {fname} ({stats['lines_added']} líneas añadidas, {stats['lines_removed']} eliminadas)",
        "cambios_tecnicos": [
            f"+{stats['lines_added']} líneas añadidas",
            f"-{stats['lines_removed']} líneas eliminadas",
            f"{stats['hunks']} secciones modificadas",
        ],
        "nivel_riesgo": risk,
        "componentes": [fname],
        "stats": stats,
    }


def generate_human_summary(file_path: str, diff: str) -> dict[str, Any]:
    """
    Use the cheap model to generate a structured JSON summary of a diff.
    Falls back to a stats-based summary if the model fails.
    """
    stats = parse_diff_stats(diff)
    diff_preview = diff[:2000] + ("…" if len(diff) > 2000 else "")

    prompt = f"""Analiza este diff para `{file_path}` y responde SOLO con JSON válido sin markdown:

{diff_preview}

JSON requerido (sin texto adicional):
{{
  "resumen_humano": "1 frase en español de negocio, sin jerga",
  "cambios_tecnicos": ["cambio 1", "cambio 2"],
  "nivel_riesgo": "bajo|medio|alto",
  "componentes": ["módulo o componente afectado"]
}}"""

    try:
        from langchain_core.messages import HumanMessage

        from .smart_router import get_cheap_model
        model = get_cheap_model()
        response = model.invoke([HumanMessage(content=prompt)])
        content = response.content
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            data = json.loads(m.group())
            data["stats"] = stats
            return data
    except Exception as exc:
        logger.warning("diff_parser: model failed: %s", exc)

    return _fallback_summary(file_path, stats)
