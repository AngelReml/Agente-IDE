import os
import json
import shutil
import logging
import asyncio
import subprocess
from pathlib import Path

# Load .env before any local imports so os.getenv() sees the values.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field

from .graph import run_swarm_stream, clear_session_messages, session_message_count
from .smart_router import current_info, all_info, reset, set_model, set_routing_mode, get_routing_mode
from .tools import PROJECT_ROOT, ensure_project, SKIP_DIRS, MAX_FILE_BYTES
from . import safe_fs, diff_parser, ast_indexer, cost_tracker
from .terminal import handle_terminal_ws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Swarm IDE API", version="3.0.0")

# CORS intentionally open — localhost dev tool only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=8000)


class FileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., max_length=2_000_000)


class ModelSelectRequest(BaseModel):
    model_id: str


class RestoreRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    timestamp: int


class DiffSummaryRequest(BaseModel):
    path: str
    diff: str = Field(..., max_length=50_000)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    info = current_info()
    return {"status": "ok", "provider": info["provider"], "model": info["model"]}


# ── Swarm Task Execution (SSE) ────────────────────────────────────────────────

@app.post("/run")
async def run_task(request: TaskRequest):
    async def generator():
        try:
            async for event in run_swarm_stream(request.task):
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            logger.info("SSE client disconnected")
        except Exception as exc:
            logger.error("Unhandled stream error: %s", exc, exc_info=True)
            yield {"data": json.dumps({"type": "error", "content": str(exc)[:300]})}

    return EventSourceResponse(generator())


# ── File System ───────────────────────────────────────────────────────────────

def _resolve_api_path(path: str) -> str:
    """Resolve a path for HTTP API endpoints (workspace-only, no traversal)."""
    return safe_fs.resolve_and_validate_path(path, allow_external=False)


def _build_tree(full: str, rel: str = ".", depth: int = 0, max_depth: int = 8):
    if depth > max_depth or not os.path.exists(full):
        return None
    name = os.path.basename(full) or "current"
    if os.path.isfile(full):
        return {"name": name, "type": "file", "path": rel}
    children = []
    try:
        entries = sorted(os.listdir(full))
        for entry in entries:
            if entry in SKIP_DIRS or (entry.startswith(".") and entry not in {".env", ".gitignore", ".dockerignore"}):
                continue
            ef = os.path.join(full, entry)
            er = (rel.rstrip("/") + "/" + entry).lstrip("./")
            child = _build_tree(ef, er, depth + 1, max_depth)
            if child:
                children.append(child)
    except PermissionError:
        pass
    return {"name": name, "type": "directory", "path": rel, "children": children}


@app.get("/api/files")
def get_files():
    ensure_project()
    return _build_tree(PROJECT_ROOT, ".")


@app.get("/api/file")
def get_file(path: str = Query(..., max_length=500)):
    ensure_project()
    try:
        full = _resolve_api_path(path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not os.path.exists(full):
        raise HTTPException(404, f"Not found: {path}")
    if os.path.isdir(full):
        raise HTTPException(400, f"{path} is a directory")
    if os.path.getsize(full) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File too large (>{MAX_FILE_BYTES//1024}KB)")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/file")
def post_file(req: FileWriteRequest):
    ensure_project()
    try:
        full = _resolve_api_path(req.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(req.content)
    return {"status": "ok", "path": req.path}


@app.delete("/api/file")
def delete_file_endpoint(path: str = Query(..., max_length=500)):
    ensure_project()
    try:
        full = _resolve_api_path(path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not os.path.exists(full):
        raise HTTPException(404, f"Not found: {path}")
    if os.path.isfile(full):
        os.remove(full)
    else:
        shutil.rmtree(full)
    return {"status": "ok", "path": path}


# ── Git ───────────────────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", PROJECT_ROOT] + list(args),
            capture_output=True, text=True, timeout=30,
        )
        return (r.stdout + "\n" + r.stderr).strip()
    except Exception as exc:
        return str(exc)


@app.get("/api/git/status")
def git_status():
    ensure_project()
    return {
        "status": _git("status", "--short") or "clean",
        "branch": _git("branch", "--show-current") or "main",
    }


@app.get("/api/git/log")
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


@app.post("/api/models/reset")
def reset_models():
    reset()
    return {"status": "ok", "current": current_info()}


@app.get("/api/routing/mode")
def get_mode():
    return {"mode": get_routing_mode()}


@app.post("/api/routing/mode")
def update_routing_mode(body: dict):
    mode = body.get("mode", "fast")
    try:
        set_routing_mode(mode)
        return {"status": "ok", "mode": mode}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/models/select")
async def select_model(req: ModelSelectRequest):
    ok = await set_model(req.model_id)
    if not ok:
        raise HTTPException(400, f"Model not found or unavailable: {req.model_id}")
    return {"status": "ok", "current": current_info()}


# ── Chat history ──────────────────────────────────────────────────────────────

@app.get("/api/chat/context")
def get_chat_context():
    return {"messages": session_message_count()}


@app.post("/api/chat/clear")
def clear_chat_context():
    clear_session_messages()
    return {"status": "ok", "messages": 0}


# ── Backup / Restore (Timeline) ───────────────────────────────────────────────

@app.get("/api/backups")
def list_backups(path: str = Query(..., max_length=500)):
    """List all backup snapshots for a file. Returns timestamps sorted newest-first."""
    ensure_project()
    try:
        backups = safe_fs.list_backups(path)
        return {"backups": [{"timestamp": ts, "backup_path": bp} for bp, ts in backups]}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/restore")
def restore_file(req: RestoreRequest):
    """Restore a file to a specific backup snapshot."""
    ensure_project()
    try:
        safe_fs.restore_backup(req.path, req.timestamp)
        return {"status": "ok", "path": req.path, "timestamp": req.timestamp}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Diff Summary ──────────────────────────────────────────────────────────────

@app.post("/api/diff/summary")
async def diff_summary(req: DiffSummaryRequest):
    """Generate a human-readable structured summary of a unified diff using the cheap model."""
    try:
        result = diff_parser.generate_human_summary(req.path, req.diff)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Semantic Index ────────────────────────────────────────────────────────────

@app.post("/api/index/rebuild")
def rebuild_index():
    """Rebuild the semantic AST index for the project."""
    ensure_project()
    result = ast_indexer.save_index(PROJECT_ROOT)
    return {"status": "ok", "message": result}


# ── Cost tracking ─────────────────────────────────────────────────────────────

@app.get("/api/cost")
def get_cost():
    return {
        "run":     cost_tracker.run_stats(),
        "session": cost_tracker.session_stats(),
    }


# ── Project workspace ─────────────────────────────────────────────────────────

class ProjectSwitchRequest(BaseModel):
    path: str

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

@app.get("/api/project")
def get_project():
    return {"path": PROJECT_ROOT}


@app.post("/api/project/switch")
def switch_project(req: ProjectSwitchRequest):
    """Update PROJECT_ROOT in .env and return the new path."""
    new_path = Path(req.path)
    if not new_path.exists():
        raise HTTPException(400, f"Path does not exist: {req.path}")
    if not new_path.is_dir():
        raise HTTPException(400, f"Path is not a directory: {req.path}")

    # Update .env file
    try:
        env_text = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
        new_line = f"PROJECT_ROOT={req.path.replace(chr(92), '/')}"
        if "PROJECT_ROOT=" in env_text:
            import re
            env_text = re.sub(r"PROJECT_ROOT=.*", new_line, env_text)
        else:
            env_text = env_text.rstrip() + f"\n{new_line}\n"
        _ENV_FILE.write_text(env_text, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(500, f"Could not update .env: {exc}")

    return {"status": "ok", "path": str(new_path), "note": "Restart backend to apply"}


@app.get("/api/project/recents")
def list_recent_projects():
    """Return directories near the current project root as quick-switch candidates."""
    try:
        parent = Path(PROJECT_ROOT).parent
        dirs = [str(d) for d in sorted(parent.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        return {"recents": dirs[:20]}
    except Exception:
        return {"recents": []}


# ── Integrated terminal (WebSocket) ──────────────────────────────────────────

@app.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    await handle_terminal_ws(websocket, PROJECT_ROOT)
