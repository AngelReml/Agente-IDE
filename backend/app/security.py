"""
Security primitives: request auth, SSRF guard, command-safety checks.

The threat model changed in v4: the backend can now be bound to the LAN
(SWARM_HOST=0.0.0.0). When it is, every mutating/executing surface must be
authenticated, and the filesystem/command/network reach must be constrained.
"""
import ipaddress
import re
import socket
import shlex
from urllib.parse import urlparse

from fastapi import Header, HTTPException, WebSocket

from . import config


# ── Request authentication ──────────────────────────────────────────────────────

def _token_ok(provided: str | None) -> bool:
    expected = config.auth_token()
    if expected is None:
        # No token configured. Allowed only when bound to loopback.
        return config.is_loopback_only()
    if not provided:
        return False
    # Accept "Bearer <token>" or the raw token.
    if provided.startswith("Bearer "):
        provided = provided[7:]
    # Constant-time-ish comparison.
    return _consteq(provided.strip(), expected)


def _consteq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency for mutating/exec endpoints."""
    if not _token_ok(authorization):
        raise HTTPException(
            status_code=401,
            detail=("Autenticación requerida. El servidor está expuesto fuera de "
                    "localhost: define SWARM_AUTH_TOKEN y envíalo en el header "
                    "Authorization."),
        )


def ws_auth_ok(websocket: WebSocket) -> bool:
    """Check a WebSocket handshake for the shared token.
    Looks at the Authorization header and the ?token= query param."""
    provided = websocket.headers.get("authorization")
    if provided is None:
        provided = websocket.query_params.get("token")
    return _token_ok(provided)


# ── SSRF guard for fetch_url ─────────────────────────────────────────────────────

def validate_outbound_url(url: str) -> str | None:
    """Return an error message if the URL must be blocked, else None."""
    if config.allow_private_fetch():
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL inválida."
    if parsed.scheme not in ("http", "https"):
        return f"Esquema no permitido: {parsed.scheme!r}. Usa http/https."
    host = parsed.hostname
    if not host:
        return "URL sin host."
    # Resolve and reject private / loopback / link-local / reserved ranges.
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return f"No se pudo resolver el host: {host}"
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return (f"Destino bloqueado por seguridad ({ip}). Las IP privadas, "
                    f"loopback y link-local están vetadas (evita SSRF). "
                    f"Define SWARM_ALLOW_PRIVATE_FETCH=1 para permitirlas.")
    return None


# ── Command-safety checks ────────────────────────────────────────────────────────
# shell=False is always used, so injection via pipes/redirects is not possible,
# but we still block genuinely destructive single commands as defence-in-depth.

_BLOCKED_PATTERNS = [
    r"\brm\b[\s\S]*-[\w]*r[\w]*\s",     # rm with a recursive flag (any order/spacing)
    r"\brmdir\b\s+/[sS]",
    r"\bdel\b\s+/[sS]",
    r"\bformat\b\s+[A-Za-z]:",
    r"\bfdisk\b", r"\bmkfs\b", r"\bdd\b\s+if=",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b",
    r":\(\)\s*\{",                       # fork bomb
    r"\bgit\b.*\bpush\b.*--force",       # destructive push
]


def blocked_command(command: str) -> str | None:
    """Return the matched dangerous pattern, or None if the command is acceptable."""
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern
    return None


def tokenize(command: str) -> list[str]:
    return shlex.split(command, posix=True)
