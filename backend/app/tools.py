import os
import sys
import json
import shutil
import subprocess
import logging
import shlex
import re
from pathlib import Path
from typing import Optional, List
from langchain_core.tools import tool

from . import safe_fs
from . import memoria_manager
from . import state_context
from . import ast_indexer
from .agents import subagents

logger = logging.getLogger(__name__)

PROJECT_ROOT: str = os.getenv(
    "PROJECT_ROOT",
    str(Path.home() / "swarm-projects" / "current"),
)

MAX_FILE_BYTES = 500_000  # 500 KB read limit

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".next",
    "venv", ".venv", ".mypy_cache", "dist", "build", ".cache", ".swarm"
})

# Whitelist de comandos permitidos (primer argumento del comando)
ALLOWED_COMMANDS = {
    # Python runtimes
    "python", "python3", "py",
    # Package managers
    "pip", "pip3",
    # Node ecosystem
    "node", "npm", "npx",
    # Version control
    "git",
    # Network utils (built-in on Windows 10+ and most Unix)
    "curl", "wget",
    # Windows shell built-ins (handled natively — ver abajo)
    "mkdir", "md", "dir", "ls", "cat", "type", "echo", "move", "copy",
    # Testing
    "pytest",
}

# Solo patrones genuinamente destructivos (no usamos shell=True, así que
# pipes/redirects son inofensivos — se pasan como args literales al proceso)
BLOCKED_PATTERNS = [
    r"\brm\b\s+-rf",        # Unix recursive delete
    r"\bdel\b\s+/[sS]",     # Windows recursive delete
    r"\bformat\b\s+[A-Za-z]:",  # Disk format
    r"\bfdisk\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
]

# Built-ins de Windows que no son ejecutables — los manejamos con Python nativo
_WIN_BUILTINS = {"mkdir", "md", "dir", "ls", "cat", "type", "echo", "move", "copy"}

def ensure_project() -> None:
    os.makedirs(PROJECT_ROOT, exist_ok=True)
    git_dir = os.path.join(PROJECT_ROOT, ".git")
    if not os.path.exists(git_dir):
        subprocess.run(["git", "init", PROJECT_ROOT], capture_output=True, check=False)
        subprocess.run(["git", "-C", PROJECT_ROOT, "config", "user.email", "swarm@ide.local"], capture_output=True)
        subprocess.run(["git", "-C", PROJECT_ROOT, "config", "user.name", "Swarm IDE"], capture_output=True)
    # Initialize memoria.md if missing
    memoria_manager.initialize_memoria_if_needed(PROJECT_ROOT)

def _check_syntax(full_path: str, path_hint: str) -> str:
    ext = path_hint.rsplit(".", 1)[-1].lower() if "." in path_hint else ""
    if ext == "py":
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", full_path],
            capture_output=True, text=True, timeout=15,
        )
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
    r = subprocess.run(
        ["git", "-C", PROJECT_ROOT] + args,
        capture_output=True, text=True, timeout=30,
    )
    return (r.stdout + "\n" + r.stderr).strip()

# ── File system tools ─────────────────────────────────────────────────────────

@tool
def list_files(path: str = ".") -> str:
    """List files and directories. Accepts absolute paths (C:\\Users\\...) or paths relative to the workspace."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
        
    if not os.path.exists(full):
        return f"Path not found: {path}"
    lines: list[str] = []
    for root, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        level = os.path.relpath(root, full).count(os.sep)
        indent = "  " * level
        folder = os.path.basename(root) if root != full else str(full)
        lines.append(f"{indent}{folder}/")
        for f in sorted(files):
            lines.append(f"{indent}  {f}")
    return "\n".join(lines) or "(empty)"

@tool
def read_file(path: str) -> str:
    """Read file content. Accepts absolute paths (C:\\Users\\...) or paths relative to the workspace."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)

    if not os.path.exists(full):
        return f"File not found: {path}"
    if os.path.isdir(full):
        return f"{path} is a directory — use list_files."
    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        return f"File too large ({size:,} bytes)."
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    # Track memoria.md reads for state guard
    if os.path.basename(full).lower() == "memoria.md":
        state_context.mark_memoria_read()
    return content

@tool
def write_file(path: str, content: str, overwrite_external: bool = False) -> str:
    """Write or overwrite a file. Auto-checks Python/JSON syntax.
    Generates backup automatically. Registers change in memoria.md."""
    ensure_project()
    
    # Check if high risk to remind agent to consult memoria.md
    if memoria_manager.is_high_risk_change("Modificación de archivo", [path]):
        # Memoria manager entry will be written, but we check if we should notify
        pass
        
    try:
        resolved, diff_out, backup_path = safe_fs.write_file_safe(path, content, overwrite_external)
    except ValueError as e:
        return (
            f"⚠️ CONFIRMACION REQUERIDA: '{path}' ya existe o está fuera del workspace.\n"
            f"Informa al usuario exactamente qué vas a cambiar y por qué. "
            f"Si confirma, vuelve a llamar write_file con overwrite_external=True."
        )
    except Exception as e:
        return f"❌ Error al escribir: {e}"
        
    verification = _check_syntax(resolved, path)
    
    # Document in memoria.md
    memoria_manager.add_changelog_entry(
        PROJECT_ROOT,
        description=f"Edición de archivo: {os.path.basename(path)}",
        files=[path],
        risk_level="Medio" if len(content) > 1000 else "Bajo",
        agent_name="Swarm-Agent-Coder"
    )
    
    # Track mutation for state guard
    state_context.add_modified_file(path)
    if os.path.basename(path).lower() == "memoria.md":
        state_context.mark_changelog_added()

    backup_msg = f" (Backup creado en {os.path.basename(backup_path)})" if backup_path else ""
    return f"✅ {path} ({len(content):,} chars){verification}{backup_msg}"

@tool
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Edit an existing file by replacing an exact string — PREFERRED over write_file for modifications.

    Provide the exact substring to replace and its replacement.
    `old_string` must be unique in the file — include enough surrounding lines to make it unique.
    Use `replace_all=True` to replace every occurrence.
    For brand-new files or complete rewrites, use write_file instead.
    """
    ensure_project()

    try:
        full_path = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)

    if not os.path.exists(full_path):
        return f"❌ Archivo no encontrado: {path}"

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"❌ No se pudo leer: {e}"

    count = content.count(old_string)
    if count == 0:
        # Give useful diagnostic — show nearby area if possible
        return (
            f"❌ Cadena no encontrada en {path}.\n"
            f"El archivo puede haber cambiado desde que lo leíste. "
            f"Usa read_file para ver el contenido actual y ajusta old_string."
        )
    if count > 1 and not replace_all:
        return (
            f"❌ La cadena aparece {count} veces. Incluye más contexto circundante "
            f"para hacerla única, o usa replace_all=True."
        )

    new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

    try:
        resolved, diff_out, backup_path = safe_fs.write_file_safe(path, new_content, overwrite_external=True)
    except Exception as e:
        return f"❌ Error al escribir: {e}"

    verification = _check_syntax(resolved, path)
    memoria_manager.add_changelog_entry(
        PROJECT_ROOT,
        description=f"Edición quirúrgica: {os.path.basename(path)}",
        files=[path],
        risk_level="Bajo",
        agent_name="Swarm-Agent-Coder",
    )
    state_context.add_modified_file(path)
    if os.path.basename(path).lower() == "memoria.md":
        state_context.mark_changelog_added()

    n_replaced = count if replace_all else 1
    backup_msg = f" (backup: {os.path.basename(str(backup_path))})" if backup_path else ""
    return f"✅ edit_file: {path} — {n_replaced} reemplazo(s){verification}{backup_msg}"


@tool
def delete_file(path: str, confirmed: bool = False) -> str:
    """Delete a file or directory recursively. Creates backup automatically."""
    ensure_project()
    try:
        resolved, is_dir = safe_fs.delete_file_safe(path, confirmed)
    except ValueError as e:
        return (
            f"⚠️ CONFIRMACION REQUERIDA: '{path}' está fuera del workspace.\n"
            f"Informa al usuario qué vas a borrar. "
            f"Si confirma, vuelve a llamar delete_file con confirmed=True."
        )
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"❌ Error al eliminar: {e}"
        
    # Document in memoria.md
    memoria_manager.add_changelog_entry(
        PROJECT_ROOT,
        description=f"Eliminación de {'directorio' if is_dir else 'archivo'}: {os.path.basename(path)}",
        files=[path],
        risk_level="Alto",
        agent_name="Swarm-Agent-Coder"
    )
    
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
    
    # Document in memoria.md
    memoria_manager.add_changelog_entry(
        PROJECT_ROOT,
        description=f"Movimiento/Renombrado: {os.path.basename(src)} -> {os.path.basename(dst)}",
        files=[src, dst],
        risk_level="Bajo",
        agent_name="Swarm-Agent-Coder"
    )
    return f"✅ Moved: {src} → {dst}"

@tool
def preview_changes(path: str, content: str) -> str:
    """Preview changes before writing them. Generates a unified diff."""
    ensure_project()
    try:
        resolved = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
        
    old_content = ""
    if os.path.exists(resolved):
        if os.path.isdir(resolved):
            return f"'{path}' es un directorio, no se puede hacer preview."
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
            
    diff = safe_fs.get_diff(old_content, content, os.path.basename(resolved))
    return diff if diff else "No hay cambios con respecto al archivo actual."

@tool
def restore_file(path: str, timestamp: int) -> str:
    """Restore a file to a previous backup snapshot using its timestamp."""
    ensure_project()
    try:
        resolved = safe_fs.restore_backup(path, timestamp)
        
        # Document in memoria.md
        memoria_manager.add_changelog_entry(
            PROJECT_ROOT,
            description=f"Restauración de backup de {os.path.basename(path)} (Timestamp {timestamp})",
            files=[path],
            risk_level="Medio",
            agent_name="Swarm-Agent-Safety"
        )
        return f"✅ Archivo '{path}' restaurado correctamente."
    except Exception as e:
        return f"❌ Error al restaurar backup: {e}"

# ── Safe Command execution (Sandbox) ──────────────────────────────────────────

@tool
def run_command(command: str, timeout: int = 120) -> str:
    """Execute a shell command inside the project workspace directory.
    Supports: python, pip, node, npm, npx, git, curl, pytest, mkdir, ls/dir.
    Tip: for complex OS tasks, write a Python script and run it with `python script.py`.
    """
    ensure_project()

    # 1. Tokenize
    try:
        args = shlex.split(command)
    except Exception as e:
        return f"❌ Error parsing command: {e}"

    if not args:
        return "❌ Comando vacío"

    cmd_name = args[0].lower() if sys.platform == "win32" else args[0]

    # 2. Check blacklist (genuinely destructive patterns — shell=False so no injection risk)
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"❌ Patrón peligroso detectado ({pattern}). Ejecución denegada."

    # 3. Native handlers for Windows shell built-ins (no executable on PATH)
    if cmd_name in ("mkdir", "md"):
        target = " ".join(args[1:]).strip().strip('"\'') if len(args) > 1 else ""
        if not target:
            return "❌ mkdir: especifica un directorio"
        p = Path(PROJECT_ROOT) / target
        try:
            p.mkdir(parents=True, exist_ok=True)
            return f"✅ Directorio creado: {p}"
        except Exception as e:
            return f"❌ mkdir: {e}"

    if cmd_name in ("dir", "ls"):
        target_path = Path(PROJECT_ROOT) / (args[1] if len(args) > 1 else ".")
        try:
            entries = sorted(target_path.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = [f"{'[DIR] ' if e.is_dir() else '      '}{e.name}" for e in entries]
            return "\n".join(lines) or "(vacío)"
        except Exception as e:
            return f"❌ ls: {e}"

    if cmd_name in ("cat", "type"):
        target = Path(PROJECT_ROOT) / (args[1] if len(args) > 1 else "")
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"❌ cat: {e}"

    if cmd_name == "echo":
        return " ".join(args[1:])

    # 4. Whitelist check for external executables
    base = os.path.basename(args[0])            # handle full paths like /usr/bin/python
    base_no_ext = base.rsplit(".", 1)[0].lower()  # strip .exe on Windows
    if base_no_ext not in {c.lower() for c in ALLOWED_COMMANDS} and cmd_name not in ALLOWED_COMMANDS:
        return (
            f"❌ Comando '{args[0]}' no está en la lista permitida.\n"
            f"Permitidos: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    # 5. Log package installs
    if cmd_name in {"pip", "pip3"} and len(args) > 1 and args[1] == "install":
        memoria_manager.add_changelog_entry(
            PROJECT_ROOT,
            description=f"pip install: {' '.join(args[2:])}",
            files=["requirements.txt"],
            risk_level="Bajo",
            agent_name="Swarm-Agent-Coder",
        )
    if cmd_name == "npm" and len(args) > 1 and args[1] in {"install", "i"}:
        memoria_manager.add_changelog_entry(
            PROJECT_ROOT,
            description=f"npm install: {' '.join(args[2:])}",
            files=["package.json"],
            risk_level="Bajo",
            agent_name="Swarm-Agent-Coder",
        )

    # 6. Resolve executable path
    executable = shutil.which(args[0]) or shutil.which(cmd_name)
    if executable:
        args[0] = executable
    else:
        return (
            f"❌ Ejecutable '{args[0]}' no encontrado en PATH.\n"
            f"Tip: usa 'python -m {cmd_name}' o instala con 'pip install {cmd_name}'."
        )

    # 7. Run
    try:
        result = subprocess.run(
            args,
            shell=False,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "CI": "true", "TERM": "dumb", "PYTHONUNBUFFERED": "1"},
        )
        out = result.stdout or ""
        err = result.stderr or ""
        combined = out
        if err:
            combined += ("\nSTDERR:\n" if out else "") + err
        status = "✅" if result.returncode == 0 else f"⚠️ exit {result.returncode}"
        return f"{status}\n{combined.strip()}" if combined.strip() else status
    except subprocess.TimeoutExpired:
        return f"❌ Timeout después de {timeout}s. Considera dividir la tarea o aumentar timeout."
    except Exception as exc:
        return f"❌ Error de ejecución: {exc}"

# ── HTTP fetch (sin dependencias externas) ────────────────────────────────────

@tool
def fetch_url(url: str, as_json: bool = False) -> str:
    """Fetch content from a URL (HTTP GET). No external packages required.
    Use for:
    - Public APIs (Open-Meteo, CoinGecko, etc.)
    - Web pages for scraping
    Set as_json=True to pretty-print JSON responses.
    Returns up to 50,000 characters.
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 SwarmIDE/3.0",
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "es,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            charset = resp.info().get_content_charset("utf-8")
            text = raw.decode(charset, errors="replace")

        if as_json:
            import json as _json
            try:
                text = _json.dumps(_json.loads(text), indent=2, ensure_ascii=False)
            except Exception:
                pass  # return raw if not valid JSON

        if len(text) > 50_000:
            text = text[:50_000] + f"\n…[truncado — {len(text):,} chars total]"

        return text

    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}: {url}"
    except urllib.error.URLError as e:
        return f"URL Error: {e.reason}"
    except Exception as e:
        return f"Error: {e}"


# ── Repository Search & Deep Understanding (repos gigantes) ────────────────────

@tool
def grep_search(query: str, path: str = ".") -> str:
    """Fast search for pattern/query recursively inside file contents in a directory.
    Uses regex matching inside files to locate references, functions, definitions, etc."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
        
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    
    count = 0
    for root, dirs, files in os.walk(full):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            file_path = os.path.join(root, file)
            # Skip large files or binary files
            if os.path.exists(file_path) and os.path.getsize(file_path) > 300_000:
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            rel = os.path.relpath(file_path, PROJECT_ROOT)
                            results.append(f"{rel}:{line_num}: {line.strip()}")
                            count += 1
                            if count >= 100:  # Cap results for context safety
                                break
            except Exception:
                pass
            if count >= 100:
                break
        if count >= 100:
            results.append("... [Truncado, demasiados resultados]")
            break
            
    return "\n".join(results) if results else "No se encontraron coincidencias."

@tool
def get_architecture_tree(path: str = ".") -> str:
    """Shows only the high level structure (directories and config files) to understand the project architecture.
    Ignores regular files to keep context small for large repositories."""
    ensure_project()
    try:
        full = safe_fs.resolve_and_validate_path(path, allow_external=True)
    except ValueError as e:
        return str(e)
        
    lines = []
    for root, dirs, files in os.walk(full):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        level = os.path.relpath(root, full).count(os.sep)
        indent = "  " * level
        folder = os.path.basename(root) if root != full else str(full)
        lines.append(f"{indent}{folder}/")
        
        # Only show configuration, requirements, package files or main files
        important_patterns = {
            r"package\.json", r"requirements\.txt", r"tsconfig\.json",
            r"\.env.*", r"docker.*", r"main\.py", r"graph\.py",
            r"index\.ts", r"page\.tsx", r"App\.tsx", r"Cargo\.toml"
        }
        for f in sorted(files):
            if any(re.match(pat, f, re.IGNORECASE) for pat in important_patterns):
                lines.append(f"{indent}  {f} [CONFIG/CRÍTICO]")
                
    return "\n".join(lines)

# ── Git tools ─────────────────────────────────────────────────────────────────

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
            rel = os.path.relpath(safe_fs.resolve_and_validate_path(path, allow_external=True), PROJECT_ROOT)
            args.append(rel)
        except ValueError:
            return "Invalid path"
    return _git(args) or "No unstaged changes"

@tool
def git_log(n: int = 10) -> str:
    """Show last N commits (oneline format)."""
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

@tool
def delegate_research(query: str) -> str:
    """Delegates a research task on a large repository to the Researcher Agent.
    Use this to synthesize structure, dependencies and main files for a complex task."""
    ensure_project()
    return subagents.run_researcher(query, PROJECT_ROOT)

@tool
def delegate_review(path: str, proposed_content: str) -> str:
    """Delegates a code review to the Reviewer Agent to verify security, performance, 
    and style before doing a write_file."""
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
    return subagents.run_reviewer(path, diff)

# ── Semantic index tools ──────────────────────────────────────────────────────

@tool
def get_semantic_map() -> str:
    """Get a human-readable map of all indexed symbols (classes, functions, types) across the project.
    Much more efficient than grep for understanding architecture before modifying code."""
    ensure_project()
    # Rebuild index if it doesn't exist or is older than 5 minutes
    idx = ast_indexer.load_index(PROJECT_ROOT)
    if not idx or (idx.get("generated_at", 0) < (int(__import__("time").time()) - 300)):
        ast_indexer.save_index(PROJECT_ROOT)
    return ast_indexer.format_semantic_map(PROJECT_ROOT)


@tool
def search_semantic_symbol(symbol: str) -> str:
    """Search for a function, class, or type by name across the indexed project.
    Returns exact file paths and line numbers. Faster and more precise than grep_search."""
    ensure_project()
    idx = ast_indexer.load_index(PROJECT_ROOT)
    if not idx:
        ast_indexer.save_index(PROJECT_ROOT)
    results = ast_indexer.search_symbol(PROJECT_ROOT, symbol)
    if not results:
        return f"No se encontró el símbolo '{symbol}' en el índice. Prueba con grep_search para búsqueda de texto."
    lines = [f"🔍 Símbolo '{symbol}' encontrado en {len(results)} lugar(es):"]
    for r in results[:20]:
        lines.append(f"  📄 {r['file']}:{r['line']}  [{r['kind']}] {r['name']}")
    return "\n".join(lines)


# ── All tools list ─────────────────────────────────────────────────────────────

ALL_TOOLS = [
    list_files,
    read_file,
    edit_file,
    write_file,
    fetch_url,
    delete_file,
    move_file,
    preview_changes,
    restore_file,
    run_command,
    grep_search,
    get_architecture_tree,
    get_semantic_map,
    search_semantic_symbol,
    delegate_research,
    delegate_review,
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_push,
    git_create_branch,
    git_checkout,
]
