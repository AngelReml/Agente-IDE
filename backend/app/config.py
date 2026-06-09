"""
Centralised configuration and constants for Swarm IDE.

All tunables live here so they can be overridden via environment variables
and so the rest of the codebase stops hard-coding magic numbers and paths.
"""
import os
import re
from pathlib import Path
from functools import lru_cache


# ── Project root (read at runtime, never cached at import-time) ─────────────────
# Reading this lazily is what makes "hot project switch" actually work: every
# call to project_root() reflects the current value of the env var.

_DEFAULT_ROOT = str(Path.home() / "swarm-projects" / "current")


def project_root() -> str:
    return os.getenv("PROJECT_ROOT", _DEFAULT_ROOT)


# ── Network / server ────────────────────────────────────────────────────────────
# Bind to loopback by default. Exposing on the LAN is now an explicit, conscious
# opt-in (SWARM_HOST=0.0.0.0) and should always be paired with SWARM_AUTH_TOKEN.

def host() -> str:
    return os.getenv("SWARM_HOST", "127.0.0.1")


def port() -> int:
    try:
        return int(os.getenv("SWARM_PORT", "8000"))
    except ValueError:
        return 8000


def auth_token() -> str | None:
    """Shared secret. If set, all mutating/exec endpoints require it.
    If unset AND host is loopback, auth is skipped (local single-user mode).
    If unset AND host is non-loopback, the server refuses to perform exec/write."""
    tok = os.getenv("SWARM_AUTH_TOKEN", "").strip()
    return tok or None


def is_loopback_only() -> bool:
    return host() in ("127.0.0.1", "localhost", "::1")


def cors_origins() -> list[str]:
    raw = os.getenv("SWARM_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Sensible default: the local Next.js dev server only.
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


# ── Filesystem limits ───────────────────────────────────────────────────────────

MAX_FILE_BYTES = 500_000          # read limit per file
MAX_GREP_FILE_BYTES = 300_000     # skip files larger than this in grep
MAX_GREP_RESULTS = 200
MAX_TREE_DEPTH = 8
MAX_LIST_ENTRIES = 5_000          # hard cap for list_files to avoid context blowups

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".next",
    "venv", ".venv", ".mypy_cache", "dist", "build", ".cache", ".swarm",
    ".pytest_cache", ".turbo", "coverage", ".gradle", "target",
})

# Files that must never be served into the file tree or opened in the editor.
SECRET_FILES = frozenset({".env", ".env.local", ".env.production", ".env.development"})

# Broader secret detection: any .env variant, private keys, credential files.
# Matched against the case-folded basename of the RESOLVED path (resists `.ENV`,
# trailing spaces and symlinks), not just the literal SECRET_FILES set.
_SECRET_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^\.env(\..+)?$",          # .env, .env.local, .env.anything
    r".*\.pem$", r".*\.key$", r".*\.pfx$", r".*\.p12$",
    r"^id_rsa.*", r"^id_ecdsa.*", r"^id_ed25519.*",
    r".*credentials?(\..+)?$", r"^\.npmrc$", r"^\.pypirc$", r"^\.git-credentials$",
))


def is_secret_path(path: str) -> bool:
    """True if `path` points at a secrets file. Resolves symlinks and compares the
    case-folded basename, so `.ENV`, `note -> .env` and `dir/.env ` are all caught."""
    try:
        base = os.path.basename(os.path.realpath(path))
    except Exception:
        base = os.path.basename(path)
    base = base.strip().lower()
    if not base:
        return False
    if base in {s.lower() for s in SECRET_FILES}:
        return True
    return any(p.match(base) for p in _SECRET_PATTERNS)


INDEXED_EXTS = frozenset({'.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java'})


# ── Agent / run limits ──────────────────────────────────────────────────────────

MAX_HISTORY = 60
MAX_TOOL_CHARS = 800
RECURSION_LIMIT = 80
LOOP_WINDOW = 8          # how many recent tool calls to inspect for loops
LOOP_WARN = 3            # warn after N repeats of the same call within the window
LOOP_ABORT = 6           # abort after N repeats

# Durable-run registry bounds (prevent unbounded memory growth in RunManager).
RUN_EVENT_BUFFER = 5_000   # max events kept in memory per run for replay
MAX_RETAINED_RUNS = 200    # max finished runs kept in memory (LRU eviction)
SESSION_TTL_SECONDS = 6 * 3600  # idle sessions pruned after this


# ── SSRF guard ──────────────────────────────────────────────────────────────────
# fetch_url refuses these unless SWARM_ALLOW_PRIVATE_FETCH=1.

def allow_private_fetch() -> bool:
    return os.getenv("SWARM_ALLOW_PRIVATE_FETCH", "0") == "1"


# ── Execution sandbox (Fase 1) ──────────────────────────────────────────────────

def sandbox_mode() -> str:
    """'local' (default), 'docker', or 'auto' (docker if available else local)."""
    return os.getenv("SWARM_SANDBOX", "local").lower()


def sandbox_image() -> str:
    return os.getenv("SWARM_SANDBOX_IMAGE", "swarm-sandbox:latest")


def sandbox_network() -> str:
    """Docker network policy for tool execution: 'none' (default, no egress) or 'bridge'."""
    return os.getenv("SWARM_SANDBOX_NETWORK", "none")


def sandbox_memory() -> str:
    return os.getenv("SWARM_SANDBOX_MEMORY", "1g")


# ── Persistence backend (Fase 2) ────────────────────────────────────────────────

def db_backend() -> str:
    """'sqlite' (default, local) or 'postgres'."""
    return os.getenv("SWARM_DB", "sqlite").lower()


def database_url() -> str:
    return os.getenv("DATABASE_URL", "")


# ── Command execution ───────────────────────────────────────────────────────────

ALLOWED_COMMANDS = frozenset({
    "python", "python3", "py",
    "pip", "pip3",
    "node", "npm", "npx", "pnpm", "yarn", "bun",
    "git",
    "curl", "wget",
    "mkdir", "md", "dir", "ls", "cat", "type", "echo", "move", "copy",
    "pytest", "ruff", "eslint", "tsc", "go", "cargo",
})

# Built-ins handled natively (no executable on PATH on Windows).
WIN_BUILTINS = frozenset({"mkdir", "md", "dir", "ls", "cat", "type", "echo", "move", "copy"})


@lru_cache(maxsize=1)
def env_file() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"
