import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

# Load .env before any local imports so os.getenv() sees the values.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import (
    ast_indexer,
    auth,
    checkpoints,
    config,
    cost_tracker,
    diff_parser,
    metrics,
    orchestrator,
    runtime,
    safe_fs,
    security,
    smart_router,
    store,
)
from .config import MAX_FILE_BYTES, SKIP_DIRS, project_root
from .graph import clear_session_messages, run_swarm_stream, session_message_count
from .platform import sandbox
from .runmanager import RunManager
from .security import require_auth
from .smart_router import all_info, current_info, get_routing_mode, reset, set_model, set_routing_mode
from .terminal import handle_terminal_ws
from .tools import ensure_project

# Durable run registry (in-process foundation; swap for Redis+workers to scale).
_runs = RunManager(run_swarm_stream)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Swarm IDE API", version="4.0.0")

_cors_origins = config.cors_origins()
# Never combine credentials with a wildcard origin (browsers reject it AND it is a
# CSRF footgun). If the operator set "*", disable credentials.
_cors_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.on_event("startup")
def _startup() -> None:
    store.init()
    ok, msg = sandbox.preflight()
    logger.info("Sandbox preflight: %s%s", msg, "" if ok else "  ⚠️")
    if not config.is_loopback_only():
        # Exposed to the network: refuse the dangerous combinations rather than
        # degrade silently. The agent can run arbitrary commands, so an exposed
        # server with the no-isolation local sandbox is remote code execution.
        if config.sandbox_mode() == "local" and os.getenv("SWARM_ALLOW_INSECURE_LOCAL_SANDBOX") != "1":
            raise RuntimeError(
                "SWARM_HOST no es loopback con SWARM_SANDBOX=local: el agente ejecutaría "
                "comandos sin aislamiento en el host (RCE). Usa SWARM_SANDBOX=docker, o "
                "fija SWARM_ALLOW_INSECURE_LOCAL_SANDBOX=1 si asumes el riesgo conscientemente.")
        if config.auth_token() is None:
            logger.warning("⚠️  SWARM_HOST no es loopback y SWARM_AUTH_TOKEN no está definido. "
                           "Los endpoints de escritura/ejecución quedarán BLOQUEADOS hasta que definas un token.")


@app.middleware("http")
async def _request_id_mw(request: Request, call_next):
    rid = request.headers.get("x-request-id") or metrics.new_request_id()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    # Label by the ROUTE TEMPLATE (e.g. /api/runs/{run_id}/events), never the raw
    # URL — otherwise every run_id/ckpt_id would create a new metric series (an
    # unbounded-cardinality memory leak, remotely inducible).
    route = request.scope.get("route")
    path_label = getattr(route, "path", None) or "other"
    metrics.M.inc("swarm_http_requests_total", path=path_label)
    return response


@app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_auth)])
def get_metrics():
    s = cost_tracker.session_stats()
    metrics.M.set_gauge("swarm_session_cost_usd", s["cost_usd"])
    metrics.M.set_gauge("swarm_session_tokens", s["input_tokens"] + s["output_tokens"])
    metrics.M.set_gauge("swarm_active_runs", len(_runs.active()))
    return metrics.M.render()


@app.get("/ready")
def readiness():
    ok, msg = sandbox.preflight()
    return {"ready": True, "sandbox": msg, "db": persistence_name()}


def persistence_name() -> str:
    from . import persistence
    return persistence.get_backend().name


# ── Models ──────────────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(default="default", max_length=64)


class FileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., max_length=2_000_000)


class ModelSelectRequest(BaseModel):
    model_id: str
    session_id: str | None = Field(default=None, max_length=64)


class RoutingModeRequest(BaseModel):
    mode: str = "fast"
    session_id: str | None = Field(default=None, max_length=64)


class RestoreRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    timestamp: int


class DiffSummaryRequest(BaseModel):
    path: str
    diff: str = Field(..., max_length=50_000)


class ProjectSwitchRequest(BaseModel):
    path: str


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    info = current_info()
    return {"status": "ok", "provider": info["provider"], "model": info["model"],
            "auth_required": not config.is_loopback_only() or config.auth_token() is not None,
            "version": "4.0.0"}


# ── Swarm Task Execution (SSE) ────────────────────────────────────────────────

def _sse(run_id: str):
    """Stream a run via the manager so the client can disconnect and reconnect."""
    async def generator():
        yield {"data": json.dumps({"type": "run", "run_id": run_id}, ensure_ascii=False)}
        try:
            async for event in _runs.subscribe(run_id):
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("SSE client disconnected (run %s continues)", run_id)
    return EventSourceResponse(generator())


@app.post("/run", dependencies=[Depends(require_auth)])
async def run_task(request: TaskRequest):
    metrics.M.inc("swarm_runs_total", mode="single")
    run_id = await _runs.start(request.task, request.session_id)
    return _sse(run_id)


@app.post("/run/swarm", dependencies=[Depends(require_auth)])
async def run_swarm_task(request: TaskRequest):
    """Parallel multi-agent run (planner → DAG → specialised agents)."""
    metrics.M.inc("swarm_runs_total", mode="swarm")
    run_id = await _runs.start(request.task, request.session_id, agent=orchestrator.run_orchestrated)
    return _sse(run_id)


@app.get("/api/runs/{run_id}/stream", dependencies=[Depends(require_auth)])
async def reconnect_run(run_id: str):
    """Reattach to an in-flight (or completed) run — replays backlog then tails."""
    if not _runs.exists(run_id):
        raise HTTPException(404, "Run desconocido o ya purgado")
    return _sse(run_id)


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_run(run_id: str):
    return {"status": "ok" if _runs.cancel(run_id) else "not_running"}


# ── File system ─────────────────────────────────────────────────────────────────

def _resolve_api_path(path: str) -> str:
    return safe_fs.resolve_and_validate_path(path, allow_external=False)


def _build_tree(full: str, rel: str = ".", depth: int = 0, max_depth: int = config.MAX_TREE_DEPTH):
    if depth > max_depth or not os.path.exists(full):
        return None
    name = os.path.basename(full) or "current"
    if os.path.isfile(full):
        return {"name": name, "type": "file", "path": rel}
    children = []
    try:
        for entry in sorted(os.listdir(full)):
            if entry in SKIP_DIRS:
                continue
            ef = os.path.join(full, entry)
            if config.is_secret_path(ef):
                continue
            if entry.startswith(".") and entry not in {".gitignore", ".dockerignore", ".env.example"}:
                continue
            er = (rel.rstrip("/") + "/" + entry).lstrip("./")
            child = _build_tree(ef, er, depth + 1, max_depth)
            if child:
                children.append(child)
    except PermissionError:
        pass
    return {"name": name, "type": "directory", "path": rel, "children": children}


@app.get("/api/files", dependencies=[Depends(require_auth)])
def get_files():
    ensure_project()
    return _build_tree(project_root(), ".")


@app.get("/api/file", dependencies=[Depends(require_auth)])
def get_file(path: str = Query(..., max_length=500)):
    ensure_project()
    try:
        full = _resolve_api_path(path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if config.is_secret_path(full):
        raise HTTPException(403, "Archivo de secretos protegido")
    if not os.path.exists(full):
        raise HTTPException(404, f"Not found: {path}")
    if os.path.isdir(full):
        raise HTTPException(400, f"{path} is a directory")
    if os.path.getsize(full) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File too large (>{MAX_FILE_BYTES//1024}KB)")
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            return {"path": path, "content": f.read()}
    except Exception:
        logger.exception("get_file failed for %s", path)
        raise HTTPException(500, "No se pudo leer el archivo")


_PROTECTED_WRITE_DIRS = (".git", ".github", ".swarm")


def _is_protected_write(full: str) -> bool:
    rel = os.path.relpath(full, project_root()).replace("\\", "/")
    first = rel.split("/", 1)[0]
    return first in _PROTECTED_WRITE_DIRS


@app.post("/api/file", dependencies=[Depends(require_auth)])
def post_file(req: FileWriteRequest):
    ensure_project()
    try:
        full = _resolve_api_path(req.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if config.is_secret_path(full):
        raise HTTPException(403, "Archivo de secretos protegido")
    if _is_protected_write(full):
        # Block writes to .git (e.g. hooks → deferred RCE), .github/workflows and .swarm.
        raise HTTPException(403, "Escritura denegada en directorio protegido (.git/.github/.swarm)")
    # Atomic, backed-up write (was a raw truncating open that could corrupt on crash).
    try:
        safe_fs.write_file_safe(req.path, req.content, overwrite_external=False)
    except Exception:
        logger.exception("post_file failed for %s", req.path)
        raise HTTPException(500, "No se pudo escribir el archivo")
    return {"status": "ok", "path": req.path}


@app.delete("/api/file", dependencies=[Depends(require_auth)])
def delete_file_endpoint(path: str = Query(..., max_length=500)):
    ensure_project()
    try:
        # delete_file_safe validates the path AND backs files up before removal,
        # so a deletion is recoverable (was a raw irreversible rmtree).
        _resolved, _is_dir = safe_fs.delete_file_safe(path, confirmed_external=False)
    except ValueError:
        raise HTTPException(400, "Ruta fuera del workspace")
    except FileNotFoundError:
        raise HTTPException(404, f"Not found: {path}")
    except Exception:
        logger.exception("delete_file failed for %s", path)
        raise HTTPException(500, "No se pudo eliminar")
    return {"status": "ok", "path": path}


# ── Git ───────────────────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", project_root()] + list(args),
                           capture_output=True, text=True, timeout=30)
        return (r.stdout + "\n" + r.stderr).strip()
    except Exception as exc:
        return str(exc)


@app.get("/api/git/status", dependencies=[Depends(require_auth)])
def git_status():
    ensure_project()
    return {"status": _git("status", "--short") or "clean",
            "branch": _git("branch", "--show-current") or "main"}


@app.get("/api/git/diff", dependencies=[Depends(require_auth)])
def git_diff_endpoint(path: str = Query(default="")):
    ensure_project()
    args = ["diff"]
    if path:
        try:
            # Confine to the project (was allow_external=True → could diff arbitrary paths).
            args.append(os.path.relpath(_resolve_api_path(path), project_root()))
        except ValueError:
            raise HTTPException(400, "Invalid path")
    return {"diff": _git(*args)}


@app.get("/api/git/log", dependencies=[Depends(require_auth)])
def git_log(n: int = Query(default=20, le=100)):
    ensure_project()
    raw = _git("log", f"-{n}", "--pretty=format:%H%x00%s%x00%an%x00%ar")
    if not raw or "fatal" in raw.lower():
        return {"commits": []}
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x00", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0][:8], "message": parts[1], "author": parts[2], "date": parts[3]})
    return {"commits": commits}


# ── Models / Provider ─────────────────────────────────────────────────────────

@app.get("/api/models")
def get_models():
    return {"current": current_info(), "chain": all_info()}


@app.post("/api/models/reset", dependencies=[Depends(require_auth)])
def reset_models():
    reset()
    return {"status": "ok", "current": current_info()}


@app.get("/api/routing/mode")
def get_mode(session_id: str | None = Query(default=None)):
    if session_id:
        sess = runtime.SESSIONS.get(session_id)
        return {"mode": sess.routing_mode or get_routing_mode()}
    return {"mode": get_routing_mode()}


@app.post("/api/routing/mode", dependencies=[Depends(require_auth)])
def update_routing_mode(req: RoutingModeRequest):
    if req.mode not in ("fast", "power"):
        raise HTTPException(400, f"Modo desconocido: {req.mode}. Usa 'fast' o 'power'.")
    if req.session_id:
        # Per-session: don't touch the global default that other sessions inherit.
        runtime.SESSIONS.get(req.session_id).routing_mode = req.mode
    else:
        set_routing_mode(req.mode)
    return {"status": "ok", "mode": req.mode}


@app.post("/api/models/select", dependencies=[Depends(require_auth)])
async def select_model(req: ModelSelectRequest):
    if not smart_router.model_available(req.model_id):
        raise HTTPException(400, f"Model not found or unavailable: {req.model_id}")
    if req.session_id:
        runtime.SESSIONS.get(req.session_id).manual_model = req.model_id
    else:
        await set_model(req.model_id)
    return {"status": "ok", "current": current_info()}


# ── Chat history ──────────────────────────────────────────────────────────────

@app.get("/api/chat/context", dependencies=[Depends(require_auth)])
def get_chat_context():
    return {"messages": session_message_count()}


@app.post("/api/chat/clear", dependencies=[Depends(require_auth)])
def clear_chat_context():
    clear_session_messages()
    return {"status": "ok", "messages": 0}


# ── Backup / Restore ──────────────────────────────────────────────────────────

@app.get("/api/backups", dependencies=[Depends(require_auth)])
def list_backups(path: str = Query(..., max_length=500)):
    ensure_project()
    try:
        backups = safe_fs.list_backups(path)
        return {"backups": [{"timestamp": ts, "backup_path": bp} for bp, ts in backups]}
    except ValueError:
        raise HTTPException(400, "Ruta fuera del workspace")
    except Exception:
        logger.exception("list_backups failed for %s", path)
        raise HTTPException(500, "No se pudieron listar los backups")


@app.post("/api/restore", dependencies=[Depends(require_auth)])
def restore_file(req: RestoreRequest):
    ensure_project()
    try:
        safe_fs.restore_backup(req.path, req.timestamp)
        return {"status": "ok", "path": req.path, "timestamp": req.timestamp}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError:
        raise HTTPException(400, "Ruta fuera del workspace")
    except Exception:
        logger.exception("restore failed for %s", req.path)
        raise HTTPException(500, "No se pudo restaurar")


# ── Checkpoints (Fase 5: time-travel de todo el workspace) ────────────────────

@app.get("/api/checkpoints", dependencies=[Depends(require_auth)])
def list_checkpoints():
    ensure_project()
    return {"checkpoints": checkpoints.list_checkpoints()}


@app.post("/api/checkpoints", dependencies=[Depends(require_auth)])
def create_checkpoint(body: dict | None = None):
    ensure_project()
    label = (body or {}).get("label", "") if isinstance(body, dict) else ""
    return checkpoints.create_checkpoint(label)


@app.post("/api/checkpoints/{ckpt_id}/restore", dependencies=[Depends(require_auth)])
def restore_checkpoint(ckpt_id: int):
    ensure_project()
    try:
        return checkpoints.restore_checkpoint(ckpt_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# ── Diff Summary ──────────────────────────────────────────────────────────────

@app.post("/api/diff/summary", dependencies=[Depends(require_auth)])
async def diff_summary(req: DiffSummaryRequest):
    try:
        return diff_parser.generate_human_summary(req.path, req.diff)
    except Exception:
        logger.exception("diff_summary failed")
        raise HTTPException(500, "No se pudo generar el resumen")


# ── Semantic Index ────────────────────────────────────────────────────────────

@app.post("/api/index/rebuild", dependencies=[Depends(require_auth)])
def rebuild_index():
    ensure_project()
    return {"status": "ok", "message": ast_indexer.save_index(project_root())}


# ── Cost tracking ─────────────────────────────────────────────────────────────

@app.get("/api/cost", dependencies=[Depends(require_auth)])
def get_cost(session_id: str | None = Query(default=None)):
    # With session_id, report that session's aggregate from its persisted runs;
    # otherwise the process-wide totals (back-compat).
    session_stats = store.session_cost(session_id) if session_id else cost_tracker.session_stats()
    return {"run": cost_tracker.run_stats(), "session": session_stats}


# ── Runs (persistence) ────────────────────────────────────────────────────────

@app.get("/api/runs", dependencies=[Depends(require_auth)])
def list_runs(session_id: str | None = Query(default=None), limit: int = Query(default=50, le=200)):
    return {"runs": store.list_runs(session_id, limit)}


@app.get("/api/runs/{run_id}/events", dependencies=[Depends(require_auth)])
def get_run_events(run_id: str):
    return {"events": store.get_run_events(run_id)}


# ── Plan (agentic task tracking) ──────────────────────────────────────────────

@app.get("/api/plan", dependencies=[Depends(require_auth)])
def get_plan():
    p = os.path.join(project_root(), ".swarm", "plan.md")
    if not os.path.exists(p):
        return {"plan": ""}
    with open(p, encoding="utf-8") as f:
        return {"plan": f.read()}


# ── Auth (Fase 3) ─────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    user_id: str = Field(default="user", max_length=64)
    workspace: str = Field(default="default", max_length=64)
    role: str = Field(default="editor")
    ttl_seconds: int = Field(default=86400, ge=60, le=2_592_000)


@app.post("/api/auth/token")
def mint_token(req: TokenRequest, principal: auth.Principal = Depends(auth.get_principal)):
    """Issue a signed token. Requires owner (the local owner in unauthenticated mode)."""
    if not principal.can("owner"):
        raise HTTPException(403, "Solo un owner puede emitir tokens")
    try:
        token = auth.issue_token(req.user_id, req.workspace, req.role, req.ttl_seconds)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"token": token, "role": req.role, "workspace": req.workspace}


@app.get("/api/auth/me")
def whoami(principal: auth.Principal = Depends(auth.get_principal)):
    return {"user_id": principal.user_id, "workspace": principal.workspace, "role": principal.role}


# ── Project workspace ─────────────────────────────────────────────────────────

@app.get("/api/project", dependencies=[Depends(require_auth)])
def get_project():
    return {"path": project_root()}


def _projects_base() -> Path | None:
    """Optional confinement dir for project switching (multi-tenant safety)."""
    base = os.getenv("SWARM_PROJECTS_DIR", "").strip()
    return Path(base).resolve() if base else None


@app.post("/api/project/switch", dependencies=[Depends(require_auth)])
def switch_project(req: ProjectSwitchRequest):
    """Update PROJECT_ROOT in .env AND in the live process so it applies immediately."""
    new_path = Path(req.path)
    if not new_path.exists():
        raise HTTPException(400, f"Path does not exist: {req.path}")
    if not new_path.is_dir():
        raise HTTPException(400, f"Path is not a directory: {req.path}")

    # If a confinement dir is configured, the new root must live under it (so a
    # token holder can't repoint PROJECT_ROOT at C:\Users and read everything).
    base = _projects_base()
    if base is not None:
        try:
            if os.path.commonpath([base, new_path.resolve()]) != str(base):
                raise HTTPException(403, "Ruta fuera del directorio de proyectos permitido")
        except ValueError:
            raise HTTPException(403, "Ruta fuera del directorio de proyectos permitido")

    normalized = str(new_path).replace("\\", "/")
    env_file = config.env_file()
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        out, found = [], False
        for line in lines:
            if line.strip().startswith("PROJECT_ROOT="):
                out.append(f"PROJECT_ROOT={normalized}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"PROJECT_ROOT={normalized}")
        env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        logger.exception("switch_project failed to update .env")
        raise HTTPException(500, "No se pudo actualizar la configuración del proyecto")

    # Apply live — config.project_root() reads env at runtime, so this is hot.
    os.environ["PROJECT_ROOT"] = normalized
    ensure_project()
    return {"status": "ok", "path": normalized, "note": "Aplicado en caliente"}


@app.get("/api/project/recents", dependencies=[Depends(require_auth)])
def list_recent_projects():
    try:
        parent = Path(project_root()).parent
        dirs = [str(d) for d in sorted(parent.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        return {"recents": dirs[:20]}
    except Exception:
        return {"recents": []}


# ── Integrated terminal (WebSocket) ──────────────────────────────────────────

@app.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    if not security.ws_auth_ok(websocket):
        await websocket.close(code=1008)
        return
    await handle_terminal_ws(websocket, project_root())
