"""
Authentication & authorization (Fase 3 foundation).

Stateless HMAC-signed tokens (stdlib only — no extra deps) carrying a principal:
user + workspace + role. RBAC is a simple ordered role check. In local loopback
mode with no secret configured, every request is the implicit local **owner**, so
nothing changes for the single-user experience; the moment you set SWARM_SECRET
(or expose the server) real tokens and role checks kick in.

The production path swaps token issuance for OAuth/OIDC and the user/workspace
store for Postgres rows — the Principal/role surface stays the same.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Depends

from . import config

# Ordered roles: index = privilege level.
ROLES = ("viewer", "editor", "owner")


def _role_level(role: str) -> int:
    try:
        return ROLES.index(role)
    except ValueError:
        return -1


def _secret() -> bytes:
    s = os.getenv("SWARM_SECRET") or config.auth_token() or ""
    return s.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class Principal:
    user_id: str
    workspace: str
    role: str

    def can(self, min_role: str) -> bool:
        return _role_level(self.role) >= _role_level(min_role)


LOCAL_OWNER = Principal(user_id="local", workspace="default", role="owner")


def issue_token(user_id: str, workspace: str = "default", role: str = "owner", ttl_seconds: int = 86400) -> str:
    if role not in ROLES:
        raise ValueError(f"Rol inválido: {role}")
    payload = {"sub": user_id, "ws": workspace, "role": role, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> Principal | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return Principal(user_id=payload["sub"], workspace=payload.get("ws", "default"),
                         role=payload.get("role", "viewer"))
    except Exception:
        return None


def _auth_active() -> bool:
    """Auth is enforced when a secret/token is configured or the server is exposed."""
    return bool(os.getenv("SWARM_SECRET")) or config.auth_token() is not None or not config.is_loopback_only()


def get_principal(authorization: str | None = Header(default=None)) -> Principal:
    """FastAPI dependency. Returns the local owner in unauthenticated local mode."""
    if not _auth_active():
        return LOCAL_OWNER
    if not authorization:
        raise HTTPException(401, "Falta token (Authorization: Bearer …)")
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    principal = verify_token(token.strip())
    if principal is None:
        raise HTTPException(401, "Token inválido o expirado")
    return principal


def require_role(min_role: str):
    """Dependency factory: enforce a minimum role on an endpoint."""
    def checker(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(min_role):
            raise HTTPException(403, f"Se requiere rol '{min_role}' o superior (tienes '{principal.role}').")
        return principal
    return checker
