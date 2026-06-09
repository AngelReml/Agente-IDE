"""
Eval harness — the quality gate for the agent (Fase Q).

Each EvalTask seeds a temp workspace, runs the agent on a prompt, and checks a
set of assertions (file exists/contains, command succeeds, no secret leak). The
assertion functions are pure and unit-tested; the agent runner is pluggable so
the harness itself can be tested with a mock and CI can run it without API keys.

Run:  python -m app.evals.harness
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

# ── Assertions (pure, testable) ─────────────────────────────────────────────────

def assert_file_exists(workspace: str, path: str) -> tuple[bool, str]:
    ok = os.path.isfile(os.path.join(workspace, path))
    return ok, f"file_exists({path})" + ("" if ok else " — NO existe")


def assert_file_contains(workspace: str, path: str, needle: str) -> tuple[bool, str]:
    full = os.path.join(workspace, path)
    if not os.path.isfile(full):
        return False, f"file_contains({path}) — archivo ausente"
    ok = needle in open(full, encoding="utf-8", errors="replace").read()
    return ok, f"file_contains({path}, {needle!r})" + ("" if ok else " — no contiene")


def assert_command_succeeds(workspace: str, cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        return ok, f"command_succeeds({' '.join(cmd)}) exit={r.returncode}"
    except Exception as e:
        return False, f"command_succeeds error: {e}"


def assert_no_secret_leak(workspace: str, transcript: str) -> tuple[bool, str]:
    leaked = any(marker in transcript for marker in ("sk-ant-", "sk-or-v1-", "AIza", "gsk_"))
    return (not leaked), "no_secret_leak" + (" — ⚠️ fuga detectada" if leaked else "")


# ── Task model ──────────────────────────────────────────────────────────────────

@dataclass
class EvalTask:
    id: str
    prompt: str
    seed_files: dict[str, str] = field(default_factory=dict)
    # each assertion: (callable, *args) applied as fn(workspace, *args)
    assertions: list[tuple] = field(default_factory=list)


# Agent runner signature: async (prompt, workspace) -> transcript str
AgentRunner = Callable[[str, str], Awaitable[str]]


@dataclass
class EvalResult:
    id: str
    passed: bool
    checks: list[tuple[bool, str]]
    error: str | None = None


async def run_task(task: EvalTask, agent: AgentRunner) -> EvalResult:
    with tempfile.TemporaryDirectory(prefix=f"eval-{task.id}-") as ws:
        for rel, content in task.seed_files.items():
            p = os.path.join(ws, rel)
            os.makedirs(os.path.dirname(p) or ws, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        try:
            transcript = await agent(task.prompt, ws)
        except Exception as e:
            return EvalResult(task.id, False, [], error=str(e)[:300])

        checks: list[tuple[bool, str]] = []
        for fn, *args in task.assertions:
            if fn is assert_no_secret_leak:
                checks.append(fn(ws, transcript))
            else:
                checks.append(fn(ws, *args))
        passed = all(ok for ok, _ in checks)
        return EvalResult(task.id, passed, checks)


async def run_all(tasks: list[EvalTask], agent: AgentRunner) -> dict:
    results = [await run_task(t, agent) for t in tasks]
    passed = sum(1 for r in results if r.passed)
    return {"total": len(results), "passed": passed,
            "results": [r.__dict__ for r in results]}


# ── Default task set (seed; grow this) ──────────────────────────────────────────

TASKS: list[EvalTask] = [
    EvalTask(
        id="create-fn",
        prompt="Crea un archivo sumar.py con una función sumar(a, b) que devuelva a+b.",
        assertions=[(assert_file_exists, "sumar.py"),
                    (assert_file_contains, "sumar.py", "def sumar"),
                    (assert_no_secret_leak,)],
    ),
    EvalTask(
        id="edit-fix",
        prompt="El archivo calc.py tiene un bug: resta en vez de sumar. Arréglalo para que sume.",
        seed_files={"calc.py": "def add(a, b):\n    return a - b\n"},
        assertions=[(assert_file_contains, "calc.py", "a + b"),
                    (assert_no_secret_leak,)],
    ),
]


# ── Real agent adapter ──────────────────────────────────────────────────────────

async def _real_agent(prompt: str, workspace: str) -> str:
    """Drives the actual swarm against a workspace. Requires API keys."""
    os.environ["PROJECT_ROOT"] = workspace
    from .. import graph
    transcript = []
    async for ev in graph.run_swarm_stream(prompt, session_id="eval"):
        transcript.append(str(ev.get("content", "")))
    return "\n".join(transcript)


def _has_keys() -> bool:
    return any(os.getenv(k) for k in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GLM_API_KEY",
        "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "HF_TOKEN", "OPENROUTER_API_KEY"))


def main() -> int:
    if not _has_keys():
        print("⏭  Sin claves API — evals omitidos (la estructura del arnés sí se valida en pytest).")
        return 0
    summary = asyncio.run(run_all(TASKS, _real_agent))
    print(f"\nEVALS: {summary['passed']}/{summary['total']} en verde")
    for r in summary["results"]:
        mark = "✅" if r["passed"] else "❌"
        print(f"  {mark} {r['id']}")
        for ok, msg in r["checks"]:
            print(f"      {'·' if ok else '✗'} {msg}")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
