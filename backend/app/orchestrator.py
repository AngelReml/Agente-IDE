"""
Multi-agent orchestration — the *real* swarm (Fase 4).

A planner decomposes the task into a DAG of role-typed subtasks; a scheduler
computes parallel batches via topological sort; specialised agents (architect,
coder, reviewer, tester) execute each batch concurrently with asyncio.gather,
sharing a blackboard. The reviewer can block. This replaces the v4.0 reality of
"one ReAct agent + two synchronous subagents".

Pure pieces (parse_plan, schedule, cycle detection) are stdlib-only and unit
tested. LLM-dependent pieces import langchain/graph lazily so the module loads
without the heavy stack.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import AsyncGenerator

from . import config

ROLES = ("architect", "coder", "reviewer", "tester")

# Tool subset per role (names resolved against tools.ALL_TOOLS at run time).
ROLE_TOOLS = {
    "architect": {"read_file", "list_files", "get_semantic_map", "search_semantic_symbol",
                  "grep_search", "get_architecture_tree", "update_plan"},
    "coder":     {"read_file", "list_files", "edit_file", "write_file", "apply_patch",
                  "move_file", "delete_file", "grep_search", "get_semantic_map", "fetch_url",
                  "run_command", "update_plan", "read_plan"},
    "reviewer":  {"read_file", "list_files", "git_diff", "grep_search", "delegate_review"},
    "tester":    {"read_file", "run_tests", "run_command", "git_status"},
}

ROLE_PROMPT = {
    "architect": "Eres el Arquitecto. Analiza y define el enfoque y los archivos a tocar. NO escribas código; produce un plan técnico claro.",
    "coder":     "Eres el Coder. Implementa el subobjetivo con edit_file/apply_patch. Código de producción, sin demos.",
    "reviewer":  "Eres el Revisor. Evalúa seguridad, arquitectura, rendimiento y corrección. Primera línea: '✅ APROBADO: …' o '❌ RECHAZADO: …'.",
    "tester":    "Eres el Tester. Ejecuta run_tests y reporta si pasa. Si falla, resume el error con precisión.",
}


@dataclass
class SubTask:
    id: str
    goal: str
    role: str = "coder"
    depends_on: list[str] = field(default_factory=list)


# ── Pure logic (unit-tested) ────────────────────────────────────────────────────

def parse_plan(raw: str) -> list[SubTask]:
    """Parse a planner's JSON (tolerant: strips markdown fences, finds the array)."""
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group())
    except Exception:
        return []
    out: list[SubTask] = []
    seen: set[str] = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or f"t{i+1}")
        if sid in seen:
            sid = f"{sid}_{i}"
        seen.add(sid)
        role = item.get("role", "coder")
        if role not in ROLES:
            role = "coder"
        deps = [str(d) for d in item.get("depends_on", []) if isinstance(d, (str, int))]
        goal = str(item.get("goal") or item.get("task") or "").strip()
        if goal:
            out.append(SubTask(id=sid, goal=goal, role=role, depends_on=deps))
    # Cap to avoid a malformed/poisoned plan spawning hundreds of agents.
    return out[:config.MAX_SUBTASKS]


def schedule(subtasks: list[SubTask]) -> list[list[SubTask]]:
    """Topological sort into parallel batches (Kahn). Raises on cycles/bad deps."""
    by_id = {s.id: s for s in subtasks}
    indeg = {s.id: 0 for s in subtasks}
    adj: dict[str, list[str]] = {s.id: [] for s in subtasks}
    for s in subtasks:
        for d in s.depends_on:
            if d not in by_id:
                raise ValueError(f"Dependencia desconocida: {d} (en {s.id})")
            indeg[s.id] += 1
            adj[d].append(s.id)

    ready = sorted([sid for sid, deg in indeg.items() if deg == 0])
    batches: list[list[SubTask]] = []
    done = 0
    while ready:
        batch_ids = ready
        batches.append([by_id[sid] for sid in batch_ids])
        done += len(batch_ids)
        nxt: list[str] = []
        for sid in batch_ids:
            for m in adj[sid]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    nxt.append(m)
        ready = sorted(nxt)
    if done != len(subtasks):
        raise ValueError("El plan contiene un ciclo de dependencias")
    return batches


MAX_GATE_RETRIES = 1


def review_rejected(review_output: str) -> bool:
    """True if a reviewer's verdict blocks the change (pure, tested)."""
    return review_output.lstrip().startswith("❌") or "RECHAZADO" in review_output.upper()


def budget_exceeded(spent_usd: float, ceiling_usd: float) -> bool:
    """True if the run has hit its cost ceiling (0 = unlimited)."""
    return ceiling_usd > 0 and spent_usd >= ceiling_usd


def render_plan(subtasks: list[SubTask]) -> str:
    lines = ["📋 Plan del enjambre:"]
    for s in subtasks:
        dep = f"  ⟵ {', '.join(s.depends_on)}" if s.depends_on else ""
        lines.append(f"  • [{s.role}] {s.id}: {s.goal}{dep}")
    return "\n".join(lines)


# ── LLM-dependent flow (lazy imports) ───────────────────────────────────────────

_PLANNER_PROMPT = """Descompón la tarea en subtareas para un equipo de agentes (architect, coder, reviewer, tester).
Responde SOLO con un array JSON de objetos: {{"id","goal","role","depends_on":[ids]}}.
Mantén 1–6 subtareas. El reviewer depende del coder; el tester depende del coder.

TAREA:
{task}"""


async def plan(task: str) -> list[SubTask]:
    """Ask a model for a DAG; fall back to a single coder subtask on any failure."""
    try:
        import asyncio
        from .smart_router import RouterState, get_heavy_model
        from langchain_core.messages import HumanMessage
        from . import graph

        def _call():
            state = RouterState(mode="power")
            entry = state.current()
            model = entry.build() if entry else get_heavy_model()
            info = entry.info() if entry else {"provider": "", "model": ""}
            msg = model.invoke([HumanMessage(content=_PLANNER_PROMPT.format(task=task))])
            return msg, info

        msg, info = await asyncio.to_thread(_call)
        try:
            graph.record_cost_from_message(msg, info)  # planner cost was billed at $0 before
        except Exception:
            pass
        raw = msg.content if hasattr(msg, "content") else str(msg)
        subtasks = parse_plan(raw if isinstance(raw, str) else str(raw))
        if subtasks:
            return subtasks
    except Exception:
        pass
    return [SubTask(id="t1", goal=task, role="coder")]


def _tools_for(role: str):
    from .tools import ALL_TOOLS
    names = ROLE_TOOLS.get(role, set())
    return [t for t in ALL_TOOLS if t.name in names] or ALL_TOOLS


async def _run_subtask(st: SubTask, root_task: str, context: dict[str, str],
                       session_id: str) -> AsyncGenerator[dict, None]:
    from langchain_core.messages import HumanMessage
    from langgraph.prebuilt import create_react_agent
    from .smart_router import RouterState, get_routing_mode
    from . import graph, config

    ctx_block = ""
    if context:
        ctx_block = "\n\nCONTEXTO DE SUBTAREAS PREVIAS:\n" + "\n".join(
            f"[{k}]\n{v[:800]}" for k, v in context.items())
    # Retrieval-augmented context for implementation roles (Fase 4).
    if st.role in ("coder", "architect"):
        try:
            from . import retrieval
            rc = retrieval.retrieve_context(st.goal, k=4)
            if rc:
                ctx_block += "\n\n" + rc
        except Exception:
            pass
    prompt = f"{ROLE_PROMPT.get(st.role, '')}\n\nOBJETIVO GLOBAL: {root_task}\n\nTU SUBTAREA: {st.goal}{ctx_block}"

    from .smart_router import is_retriable
    state = RouterState(mode=get_routing_mode())
    # Per-subtask model fallback: a 429/quota error advances to the next model
    # instead of killing the subtask (the single-agent path already did this; the
    # swarm used to lack it, so one provider hiccup tumbled a whole subtask).
    while True:
        entry = state.current()
        if entry is None:
            yield {"type": "error", "content": f"{st.id}: sin modelos disponibles"}
            return
        info = entry.info()
        try:
            agent = create_react_agent(model=entry.build(), tools=_tools_for(st.role), prompt=prompt)
            async for event in agent.astream_events(
                    {"messages": [HumanMessage(content=st.goal)]},
                    version="v2", config={"recursion_limit": config.RECURSION_LIMIT}):
                cost_ev = graph.record_cost_from_event(event, info)
                if cost_ev:
                    yield cost_ev
                parsed = graph._parse_event(event, info)
                if parsed:
                    yield parsed
            return  # subtask completed
        except Exception as exc:
            nxt = state.advance()
            if nxt is None:
                yield {"type": "error", "content": f"{st.id}: {str(exc)[:160]} — sin más modelos"}
                return
            verb = "sin créditos" if is_retriable(exc) else "error"
            yield {"type": "info",
                   "content": f"⚡ {st.id}: {info['display']} {verb} → {nxt.display_name}"}


async def run_orchestrated(task: str, session_id: str = "default") -> AsyncGenerator[dict, None]:
    import asyncio

    yield {"type": "info", "content": "🧠 Planificando el enjambre…"}
    subtasks = await plan(task)
    yield {"type": "plan", "content": render_plan(subtasks), "plan": [s.__dict__ for s in subtasks]}

    try:
        batches = schedule(subtasks)
    except ValueError as e:
        yield {"type": "error", "content": f"Plan inválido: {e}"}
        yield {"type": "done", "content": ""}
        return

    # If the plan has a reviewer, snapshot the workspace BEFORE any change so the
    # review gate can roll the whole change-set back if it ultimately rejects it
    # (before, a rejected change stayed on disk — the gate had no teeth).
    baseline_id = None
    if any(s.role == "reviewer" for s in subtasks):
        try:
            from . import checkpoints
            baseline_id = checkpoints.create_checkpoint(f"pre-swarm: {task[:60]}")["id"]
        except Exception:
            baseline_id = None
    blocked = False

    sem = asyncio.Semaphore(config.MAX_SWARM_CONCURRENCY)
    blackboard: dict[str, str] = {}
    for bi, batch in enumerate(batches):
        yield {"type": "info", "content": f"▶ Batch {bi+1}/{len(batches)}: {', '.join(s.id for s in batch)} (paralelo)"}
        queue: asyncio.Queue = asyncio.Queue()

        async def worker(st: SubTask):
            ctx = {d: blackboard.get(d, "") for d in st.depends_on}
            try:
                async with sem:  # cap concurrent subagents within the batch
                    async for ev in _run_subtask(st, task, ctx, session_id):
                        await queue.put((st.id, ev))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # pragma: no cover
                await queue.put((st.id, {"type": "error", "content": f"{st.id}: {str(e)[:200]}"}))
            finally:
                await queue.put((st.id, None))

        workers = [asyncio.create_task(worker(s)) for s in batch]
        remaining = len(batch)
        outputs: dict[str, str] = {}
        try:
            while remaining:
                sid, ev = await queue.get()
                if ev is None:
                    remaining -= 1
                    continue
                if ev.get("type") == "final":
                    outputs[sid] = ev.get("content", "")
                yield {**ev, "subtask": sid}
        finally:
            # If the consumer is cancelled (client disconnected), don't leave the
            # subagents running — they'd keep burning tokens and touching disk.
            for w in workers:
                if not w.done():
                    w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        blackboard.update(outputs)

        # Review gate (Fase 4): on rejection, re-run the reviewed coders with the
        # feedback and re-review, bounded by MAX_GATE_RETRIES.
        for s in batch:
            if s.role != "reviewer" or not review_rejected(outputs.get(s.id, "")):
                continue
            feedback = outputs.get(s.id, "")
            approved = False
            for attempt in range(1, MAX_GATE_RETRIES + 1):
                yield {"type": "info", "content": f"🚧 {s.id} RECHAZÓ — reintento {attempt}: re-codificando y revisando"}
                for dep_id in s.depends_on:
                    dep = next((x for x in subtasks if x.id == dep_id and x.role == "coder"), None)
                    if not dep:
                        continue
                    dctx = {d: blackboard.get(d, "") for d in dep.depends_on}
                    dctx["review_feedback"] = feedback
                    async for ev in _run_subtask(dep, task, dctx, session_id):
                        if ev.get("type") == "final":
                            blackboard[dep.id] = ev.get("content", "")
                        yield {**ev, "subtask": dep.id}
                new_review = ""
                async for ev in _run_subtask(s, task, {d: blackboard.get(d, "") for d in s.depends_on}, session_id):
                    if ev.get("type") == "final":
                        new_review = ev.get("content", "")
                    yield {**ev, "subtask": s.id}
                if not review_rejected(new_review):
                    approved = True
                    yield {"type": "info", "content": f"✅ {s.id} APROBÓ tras reintento"}
                    break
            if not approved:
                blocked = True
                yield {"type": "info", "content": f"⛔ {s.id} sigue rechazando tras {MAX_GATE_RETRIES} reintento(s)"}

    if blocked and baseline_id is not None:
        # The review gate now has teeth: undo the rejected change-set entirely.
        try:
            from . import checkpoints
            res = checkpoints.restore_checkpoint(baseline_id, prune=True)
            yield {"type": "info",
                   "content": (f"↩️ Revisión bloqueó el cambio: workspace revertido al estado previo "
                               f"({res['restored']} restaurados, {res['pruned']} creados eliminados).")}
        except Exception as e:
            yield {"type": "info", "content": f"⚠️ No se pudo revertir automáticamente: {str(e)[:120]}"}
        yield {"type": "done", "content": "⛔ Enjambre bloqueado por revisión — cambios deshechos"}
        return

    yield {"type": "done", "content": "✅ Enjambre completado"}
