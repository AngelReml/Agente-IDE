import os
import sys
import json
import shutil
import subprocess
import logging
import re
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

from . import safe_fs, memoria_manager, state_context, ast_indexer, config, security
from .agents import subagents
from .config import project_root, SKIP_DIRS, MAX_FILE_BYTES

logger = logging.getLogger(__name__)


def ensure_project() -> None:
    root = project_root()
    os.makedirs(root, exist_ok=True)
    if not os.path.exists(os.path.join(root, ".git")):
        subprocess.run(["git", "init", root], capture_output=True, check=False)
        subprocess.run(["git", "-C", root, "config", "user.email", "swarm@ide.local"], capture_output=True)
        subprocess.run(["git", "-C", root, "config", "user.name", "Swarm IDE"], capture_output=True)
    memoria_manager.initialize_memoria_if_needed(root)


def _check_syntax(full_path: str, path_hint: str) -> str:
    ext = path_hint.rsplit(".", 1)[-1].lower() if "." in path_hint else ""
    if ext == "py":
        r = subprocess.run([sys.executable, "-m", "py_compile", full_path],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return f"\n⚠️ SYNTAX ERROR — corrígelo antes de continuar:\n{r.stderr.strip()}"
        return "\n✅ syntax OK"
    if ext == "json":
        try:
            with open(full_path, encoding="utf-8") as f:
                json.load(f)
            return "\n✅ JSON valid"
        except json.JSONDecodeError as exc:
            return f"\n⚠️ INVALID JSON: {exc}"
    return ""


def _git(args: list) -> str:
    r = subprocess.run(["git", "-C", project_root()] + args,
                       capture_output=True, text=True, timeout=30)
    return (r.stdout + "\n" + r.stderr).strip()


def _is_secret(path: str) -> bool:
    # Resolve symlinks + case-fold the basename, and match .env*/keys/credentials —
    # not just an exact basename, which `.ENV`, trailing spaces or a symlink evade.
    return config.is_secret_path(path)


# ── File system tools ─────────────────────────────────────────────────────────

@tool
def list_files(path: str = ".") -> str:
    """List files and directories. Accepts absolute paths or workspace-relative paths."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    if not os.path.exists(full):
        return f"Path not found: {path}"
    lines: list[str] = []
    count = 0
    for root, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        level = os.path.relpath(root, full).count(os.sep)
        indent = "  " * level
        folder = os.path.basename(root) if root != full else str(full)
        lines.append(f"{indent}{folder}/")
        for f in sorted(files):
            lines.append(f"{indent}  {f}")
            count += 1
            if count >= config.MAX_LIST_ENTRIES:
                lines.append("… [truncado: demasiados archivos]")
                return "\n".join(lines)
    return "\n".join(lines) or "(empty)"


@tool
def read_file(path: str) -> str:
    """Read file content. Accepts absolute paths or workspace-relative paths."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    if _is_secret(full):
        return ("🔒 Acceso denegado: este archivo contiene secretos (claves API). "
                "No se puede leer desde el agente.")
    if not os.path.exists(full):
        return f"File not found: {path}"
    if os.path.isdir(full):
        return f"{path} is a directory — use list_files."
    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        return f"File too large ({size:,} bytes)."
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if os.path.basename(full).lower() == "memoria.md":
        state_context.mark_memoria_read()
    return content


@tool
def write_file(path: str, content: str, overwrite_external: bool = False) -> str:
    """Write or overwrite a file. Auto-checks Python/JSON syntax, backs up, logs to memoria.md."""
    ensure_project()
    if _is_secret(path):
        return "🔒 Escritura denegada: no se permite que el agente modifique archivos de secretos."

    high_risk = memoria_manager.is_high_risk_change("Modificación de archivo", [path])
    try:
        resolved, _diff, backup_path = safe_fs.write_file_safe(path, content, overwrite_external)
    except ValueError:
        return (f"⚠️ CONFIRMACION REQUERIDA: '{path}' ya existe o está fuera del workspace.\n"
                f"Informa al usuario qué vas a cambiar y por qué. "
                f"Si confirma, vuelve a llamar write_file con overwrite_external=True.")
    except Exception as e:
        return f"❌ Error al escribir: {e}"

    verification = _check_syntax(resolved, path)
    memoria_manager.add_changelog_entry(
        project_root(), description=f"Edición de archivo: {os.path.basename(path)}",
        files=[path], risk_level="Medio" if len(content) > 1000 else "Bajo",
        agent_name="Swarm-Agent-Coder")
    state_context.add_modified_file(path)
    if os.path.basename(path).lower() == "memoria.md":
        state_context.mark_changelog_added()

    backup_msg = f" (backup: {os.path.basename(backup_path)})" if backup_path else ""
    risk_msg = "\n⚠️ Cambio de ALTO RIESGO — revisa memoria.md y considera delegate_review." if high_risk else ""
    return f"✅ {path} ({len(content):,} chars){verification}{backup_msg}{risk_msg}"


@tool
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit an existing file by replacing an exact string — PREFERRED over write_file for modifications.

    `old_string` must be unique unless replace_all=True. For new files use write_file.
    """
    ensure_project()
    if _is_secret(path):
        return "🔒 Edición denegada: archivo de secretos protegido."
    try:
        full_path = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    if not os.path.exists(full_path):
        return f"❌ Archivo no encontrado: {path}"
    try:
        # Strict UTF-8: a read-modify-write with errors="replace" would silently
        # turn undecodable bytes into U+FFFD and PERSIST that, corrupting the file.
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return (f"❌ {path} no es UTF-8 válido; editarlo lo corrompería. "
                f"Edítalo manualmente o reescríbelo con write_file si es intencional.")
    except Exception as e:
        return f"❌ No se pudo leer: {e}"

    count = content.count(old_string)
    if count == 0:
        return (f"❌ Cadena no encontrada en {path}. El archivo puede haber cambiado. "
                f"Usa read_file para ver el contenido actual y ajusta old_string.")
    if count > 1 and not replace_all:
        return (f"❌ La cadena aparece {count} veces. Incluye más contexto para hacerla única "
                f"o usa replace_all=True.")

    new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    try:
        resolved, _diff, backup_path = safe_fs.write_file_safe(path, new_content, overwrite_external=True)
    except Exception as e:
        return f"❌ Error al escribir: {e}"

    verification = _check_syntax(resolved, path)
    memoria_manager.add_changelog_entry(
        project_root(), description=f"Edición quirúrgica: {os.path.basename(path)}",
        files=[path], risk_level="Bajo", agent_name="Swarm-Agent-Coder")
    state_context.add_modified_file(path)
    if os.path.basename(path).lower() == "memoria.md":
        state_context.mark_changelog_added()

    n = count if replace_all else 1
    backup_msg = f" (backup: {os.path.basename(str(backup_path))})" if backup_path else ""
    return f"✅ edit_file: {path} — {n} reemplazo(s){verification}{backup_msg}"


@tool
def apply_patch(patch: str) -> str:
    """Apply MULTIPLE edits across one or more files in a single atomic-ish operation.

    `patch` is a JSON array of objects: [{"path": "...", "old_string": "...",
    "new_string": "...", "replace_all": false}, ...]. Each entry is validated
    against the current file content BEFORE anything is written; if any entry
    fails to match, nothing is applied. Far more efficient than many edit_file
    calls for multi-file refactors.
    """
    ensure_project()
    try:
        entries = json.loads(patch)
        assert isinstance(entries, list)
    except Exception:
        return "❌ apply_patch: `patch` debe ser un array JSON de objetos {path, old_string, new_string}."

    # Phase 1 — validate everything (dry run, accumulate per-file new content).
    staged: dict[str, str] = {}
    for i, e in enumerate(entries):
        path = e.get("path", "")
        old = e.get("old_string", "")
        new = e.get("new_string", "")
        replace_all = bool(e.get("replace_all", False))
        if _is_secret(path):
            return f"❌ apply_patch[{i}]: archivo de secretos protegido ({path})."
        try:
            full = safe_fs.resolve_and_validate_path(path, allow_external=True)
        except ValueError as ex:
            return f"❌ apply_patch[{i}]: {ex}"
        if not os.path.exists(full):
            return f"❌ apply_patch[{i}]: archivo no encontrado: {path}"
        base = staged.get(full)
        if base is None:
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    base = fh.read()
            except UnicodeDecodeError:
                return f"❌ apply_patch[{i}]: {path} no es UTF-8 válido; no se edita para no corromperlo."
        cnt = base.count(old)
        if cnt == 0:
            return f"❌ apply_patch[{i}]: cadena no encontrada en {path}."
        if cnt > 1 and not replace_all:
            return f"❌ apply_patch[{i}]: cadena ambigua ({cnt}×) en {path}; usa replace_all o más contexto."
        staged[full] = base.replace(old, new) if replace_all else base.replace(old, new, 1)

    # Phase 2 — commit.
    results = []
    for full, content in staged.items():
        try:
            resolved, _d, backup = safe_fs.write_file_safe(full, content, overwrite_external=True)
            verification = _check_syntax(resolved, full)
            state_context.add_modified_file(full)
            results.append(f"✅ {os.path.relpath(full, project_root())}{verification}")
        except Exception as ex:
            results.append(f"❌ {full}: {ex}")
    memoria_manager.add_changelog_entry(
        project_root(), description=f"apply_patch: {len(staged)} archivo(s)",
        files=list(staged.keys()), risk_level="Medio", agent_name="Swarm-Agent-Coder")
    return f"apply_patch — {len(staged)} archivo(s):\n" + "\n".join(results)


@tool
def delete_file(path: str, confirmed: bool = False) -> str:
    """Delete a file or directory recursively. Creates backup automatically."""
    ensure_project()
    try:
        resolved, is_dir = safe_fs.delete_file_safe(path, confirmed)
    except ValueError:
        return (f"⚠️ CONFIRMACION REQUERIDA: '{path}' está fuera del workspace.\n"
                f"Informa al usuario qué vas a borrar. Si confirma, llama delete_file con confirmed=True.")
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"❌ Error al eliminar: {e}"
    memoria_manager.add_changelog_entry(
        project_root(), description=f"Eliminación de {'directorio' if is_dir else 'archivo'}: {os.path.basename(path)}",
        files=[path], risk_level="Alto", agent_name="Swarm-Agent-Coder")
    return f"✅ Deleted {'directory' if is_dir else 'file'}: {path} (backups guardados)"


@tool
def move_file(src: str, dst: str) -> str:
    """Move or rename a file/directory. Accepts absolute or workspace-relative paths."""
    ensure_project()
    try:
        full_src = safe_fs.resolve_and_validate_path(src, allow_external=True)
        full_dst = safe_fs.resolve_and_validate_path(dst, allow_external=True)
    except ValueError as e:
        return str(e)
    if not os.path.exists(full_src):
        return f"Source not found: {src}"
    os.makedirs(os.path.dirname(full_dst) or ".", exist_ok=True)
    shutil.move(full_src, full_dst)
    memoria_manager.add_changelog_entry(
        project_root(), description=f"Movimiento/Renombrado: {os.path.basename(src)} -> {os.path.basename(dst)}",
        files=[src, dst], risk_level="Bajo", agent_name="Swarm-Agent-Coder")
    return f"✅ Moved: {src} → {dst}"


@tool
def preview_changes(path: str, content: str) -> str:
    """Preview a write as a unified diff WITHOUT writing. Useful before a risky write_file."""
    ensure_project()
    try:
        resolved = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    old_content = ""
    if os.path.exists(resolved):
        if os.path.isdir(resolved):
            return f"'{path}' es un directorio."
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
    diff = safe_fs.get_diff(old_content, content, os.path.basename(resolved))
    return diff or "No hay cambios respecto al archivo actual."


# ── Plan / TODO (agentic task tracking) ────────────────────────────────────────

def _plan_path() -> str:
    d = os.path.join(project_root(), ".swarm")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "plan.md")


@tool
def update_plan(plan: str) -> str:
    """Record/replace the agent's working plan (a markdown checklist of steps).

    Use at the start of any multi-step task and update it as steps complete.
    Format suggestion: '- [x] done step' / '- [ ] pending step'. Persisted so the
    user can see it in the UI and the agent can re-read it next turn.
    """
    ensure_project()
    try:
        with open(_plan_path(), "w", encoding="utf-8") as f:
            f.write(plan.strip() + "\n")
        return f"✅ Plan actualizado ({plan.count(chr(10)) + 1} líneas)."
    except Exception as e:
        return f"❌ No se pudo guardar el plan: {e}"


@tool
def read_plan() -> str:
    """Read the current working plan, if any."""
    ensure_project()
    p = _plan_path()
    if not os.path.exists(p):
        return "No hay plan activo. Crea uno con update_plan."
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# ── Command execution ──────────────────────────────────────────────────────────

@tool
def run_command(command: str, timeout: int = 120) -> str:
    """Execute a shell command inside the project workspace.
    Supports: python, pip, node, npm/pnpm/yarn, npx, git, curl, pytest, ruff, tsc, mkdir, ls/dir.
    For complex OS tasks, write a Python script and run it with `python script.py`.
    """
    ensure_project()
    try:
        args = security.tokenize(command)
    except Exception as e:
        return f"❌ Error parsing command: {e}"
    if not args:
        return "❌ Comando vacío"

    cmd_name = args[0].lower() if sys.platform == "win32" else args[0]

    blocked = security.blocked_command(command)
    if blocked:
        return f"❌ Patrón peligroso detectado ({blocked}). Ejecución denegada."

    root = project_root()
    if cmd_name in ("mkdir", "md"):
        target = " ".join(args[1:]).strip().strip('"\'')
        if not target:
            return "❌ mkdir: especifica un directorio"
        try:
            (Path(root) / target).mkdir(parents=True, exist_ok=True)
            return f"✅ Directorio creado: {target}"
        except Exception as e:
            return f"❌ mkdir: {e}"
    if cmd_name in ("dir", "ls"):
        target_path = Path(root) / (args[1] if len(args) > 1 else ".")
        try:
            entries = sorted(target_path.iterdir(), key=lambda x: (x.is_file(), x.name))
            return "\n".join(f"{'[DIR] ' if e.is_dir() else '      '}{e.name}" for e in entries) or "(vacío)"
        except Exception as e:
            return f"❌ ls: {e}"
    if cmd_name in ("cat", "type"):
        target = Path(root) / (args[1] if len(args) > 1 else "")
        if _is_secret(str(target)):
            return "🔒 Acceso denegado a archivo de secretos."
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"❌ cat: {e}"
    if cmd_name == "echo":
        return " ".join(args[1:])

    base = os.path.basename(args[0])
    base_no_ext = base.rsplit(".", 1)[0].lower()
    allowed = {c.lower() for c in config.ALLOWED_COMMANDS}
    if base_no_ext not in allowed and cmd_name not in config.ALLOWED_COMMANDS:
        return (f"❌ Comando '{args[0]}' no permitido.\nPermitidos: {', '.join(sorted(config.ALLOWED_COMMANDS))}")

    if cmd_name in {"pip", "pip3"} and len(args) > 1 and args[1] == "install":
        memoria_manager.add_changelog_entry(root, description=f"pip install: {' '.join(args[2:])}",
                                             files=["requirements.txt"], risk_level="Bajo", agent_name="Swarm-Agent-Coder")
    if cmd_name in {"npm", "pnpm", "yarn"} and len(args) > 1 and args[1] in {"install", "i", "add"}:
        memoria_manager.add_changelog_entry(root, description=f"{cmd_name} install: {' '.join(args[2:])}",
                                             files=["package.json"], risk_level="Bajo", agent_name="Swarm-Agent-Coder")

    # Execute through the configured sandbox backend (local by default; docker
    # when SWARM_SANDBOX=docker/auto). The backend resolves the executable.
    from .platform import sandbox
    backend = sandbox.get_backend()
    res = backend.run(args, cwd=root, timeout=timeout)
    out, err = res.stdout, res.stderr
    if res.returncode == 127 and "no encontrado" in err:
        return f"❌ {err.strip()}\nTip: usa 'python -m {cmd_name}' o instala con pip."
    combined = out + (("\nSTDERR:\n" if out else "") + err if err else "")
    status = "✅" if res.returncode == 0 else f"⚠️ exit {res.returncode}"
    tag = f" [{backend.name}]" if getattr(backend, "name", "local") != "local" else ""
    return f"{status}{tag}\n{combined.strip()}" if combined.strip() else f"{status}{tag}"


@tool
def run_tests(target: str = "") -> str:
    """Auto-detect and run the project's test suite (pytest or npm/pnpm test).

    Pass `target` to scope it (e.g. a path for pytest, a script for npm). Returns
    the test output. Use this after edits to verify before git_commit.
    """
    ensure_project()
    root = project_root()
    if os.path.exists(os.path.join(root, "package.json")):
        cmd = f"npm test {target}".strip()
    elif (os.path.exists(os.path.join(root, "pytest.ini")) or os.path.exists(os.path.join(root, "pyproject.toml"))
          or os.path.exists(os.path.join(root, "tests")) or target.endswith(".py")):
        cmd = f"python -m pytest {target} -q".strip()
    else:
        return "No se detectó framework de tests (ni package.json ni pytest). Especifica un comando con run_command."
    return run_command.invoke({"command": cmd, "timeout": 300})


# ── HTTP fetch (SSRF-guarded) ──────────────────────────────────────────────────

@tool
def fetch_url(url: str, as_json: bool = False) -> str:
    """Fetch content from a URL (HTTP GET). No external packages required.
    Private/loopback/link-local destinations are blocked (SSRF protection).
    Set as_json=True to pretty-print JSON. Returns up to 50,000 characters.
    """
    import urllib.request
    import urllib.error

    blocked = security.validate_outbound_url(url)
    if blocked:
        return f"❌ {blocked}"

    class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
        # Re-validate every redirect target — otherwise a public URL could 3xx to
        # 169.254.169.254 / a private IP that the initial check never saw (SSRF).
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if security.validate_outbound_url(newurl):
                raise urllib.error.HTTPError(newurl, code, "Redirección bloqueada (SSRF)", headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 SwarmIDE/4.0",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "es,en;q=0.9",
        })
        opener = urllib.request.build_opener(_GuardedRedirect)
        with opener.open(req, timeout=20) as resp:
            raw = resp.read()
            charset = resp.info().get_content_charset("utf-8")
            text = raw.decode(charset, errors="replace")
        if as_json:
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except Exception:
                pass
        if len(text) > 50_000:
            text = text[:50_000] + f"\n…[truncado — {len(text):,} chars total]"
        return text
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}: {url}"
    except urllib.error.URLError as e:
        return f"URL Error: {e.reason}"
    except Exception as e:
        return f"Error: {e}"


# ── Search / understanding ─────────────────────────────────────────────────────

@tool
def grep_search(query: str, path: str = ".") -> str:
    """Fast recursive regex search inside file contents."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    results = []
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    count = 0
    for root, dirs, files in os.walk(full):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            fp = os.path.join(root, file)
            if _is_secret(fp):
                continue
            try:
                if os.path.getsize(fp) > config.MAX_GREP_FILE_BYTES:
                    continue
            except OSError:
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for ln, line in enumerate(f, 1):
                        if pattern.search(line):
                            results.append(f"{os.path.relpath(fp, project_root())}:{ln}: {line.strip()}")
                            count += 1
                            if count >= config.MAX_GREP_RESULTS:
                                break
            except Exception:
                pass
            if count >= config.MAX_GREP_RESULTS:
                break
        if count >= config.MAX_GREP_RESULTS:
            results.append("... [Truncado, demasiados resultados]")
            break
    return "\n".join(results) if results else "No se encontraron coincidencias."


@tool
def get_architecture_tree(path: str = ".") -> str:
    """Show only directories and key config/entry files for a high-level architecture view."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    lines = []
    important = {r"package\.json", r"requirements\.txt", r"pyproject\.toml", r"tsconfig\.json",
                r"\.env\.example", r"docker.*", r"main\.py", r"graph\.py", r"index\.ts",
                r"page\.tsx", r"App\.tsx", r"Cargo\.toml", r"go\.mod"}
    for root, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        level = os.path.relpath(root, full).count(os.sep)
        indent = "  " * level
        folder = os.path.basename(root) if root != full else str(full)
        lines.append(f"{indent}{folder}/")
        for f in sorted(files):
            if any(re.match(pat, f, re.IGNORECASE) for pat in important):
                lines.append(f"{indent}  {f} [CONFIG/CRÍTICO]")
    return "\n".join(lines)


# ── Git tools ──────────────────────────────────────────────────────────────────

@tool
def git_status() -> str:
    """Show current git working tree status."""
    ensure_project()
    return _git(["status", "--short"]) or "Working tree clean"


@tool
def git_diff(path: Optional[str] = None) -> str:
    """Show unstaged diff. Pass path for a specific file."""
    ensure_project()
    args = ["diff"]
    if path:
        try:
            args.append(os.path.relpath(safe_fs.resolve_and_validate_path(path, allow_external=True), project_root()))
        except ValueError:
            return "Invalid path"
    return _git(args) or "No unstaged changes"


@tool
def git_log(n: int = 10) -> str:
    """Show last N commits (oneline)."""
    ensure_project()
    return _git(["log", f"-{min(n, 50)}", "--oneline", "--decorate"]) or "No commits yet"


@tool
def git_commit(message: str) -> str:
    """Stage all changes and create a git commit."""
    ensure_project()
    _git(["add", "-A"])
    result = _git(["commit", "-m", message])
    if "nothing to commit" in result.lower():
        return "ℹ️ Nothing to commit"
    return f"✅ {result}"


@tool
def git_push(branch: str = "main") -> str:
    """Push to origin."""
    ensure_project()
    result = _git(["push", "origin", branch])
    if "error" in result.lower() or "fatal" in result.lower():
        return f"⚠️ Push failed: {result}"
    return f"✅ Pushed to {branch}"


@tool
def git_create_branch(name: str) -> str:
    """Create and switch to a new branch."""
    ensure_project()
    return _git(["checkout", "-b", name])


@tool
def git_checkout(ref: str) -> str:
    """Switch to existing branch or commit."""
    ensure_project()
    return _git(["checkout", ref])


# ── Subagent delegation (async, non-blocking) ──────────────────────────────────

@tool
async def delegate_research(query: str) -> str:
    """Delegate research on a large repo to the Researcher subagent (cheap model, async)."""
    ensure_project()
    return await subagents.run_researcher(query, project_root())


@tool
async def delegate_review(path: str, proposed_content: str) -> str:
    """Delegate a code review (security/architecture/perf/correctness) before writing."""
    ensure_project()
    try:
        resolved = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
    old_content = ""
    if os.path.exists(resolved):
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
    diff = safe_fs.get_diff(old_content, proposed_content, os.path.basename(resolved))
    if not diff:
        return "No hay cambios propuestos para revisar."
    return await subagents.run_reviewer(path, diff)


# ── Semantic index tools ───────────────────────────────────────────────────────

@tool
def get_semantic_map() -> str:
    """Human-readable map of indexed symbols (classes, functions, types) across the project."""
    ensure_project()
    import time as _t
    idx = ast_indexer.load_index(project_root())
    if not idx or (idx.get("generated_at", 0) < int(_t.time()) - 300):
        ast_indexer.save_index(project_root())
    return ast_indexer.format_semantic_map(project_root())


@tool
def search_semantic_symbol(symbol: str) -> str:
    """Search a function/class/type by name across the indexed project (exact file:line)."""
    ensure_project()
    if not ast_indexer.load_index(project_root()):
        ast_indexer.save_index(project_root())
    results = ast_indexer.search_symbol(project_root(), symbol)
    if not results:
        return f"No se encontró el símbolo '{symbol}'. Prueba grep_search."
    lines = [f"🔍 Símbolo '{symbol}' en {len(results)} lugar(es):"]
    for r in results[:20]:
        lines.append(f"  📄 {r['file']}:{r['line']}  [{r['kind']}] {r['name']}")
    return "\n".join(lines)


# ── All tools ──────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    list_files, read_file, edit_file, write_file, apply_patch, fetch_url,
    delete_file, move_file, preview_changes,
    update_plan, read_plan,
    run_command, run_tests,
    grep_search, get_architecture_tree, get_semantic_map, search_semantic_symbol,
    delegate_research, delegate_review,
    git_status, git_diff, git_log, git_commit, git_push, git_create_branch, git_checkout,
]
