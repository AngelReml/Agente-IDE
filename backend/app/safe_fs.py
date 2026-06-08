"""
Safe filesystem operations with automatic timestamped backups.

PROJECT_ROOT is now read at runtime (via config) instead of being frozen at
import time, so switching projects no longer leaves stale roots behind. Backup
storage uses a hashed bucket per file to make backup-dir escape impossible.
"""
import hashlib
import os
import shutil
import time
import difflib
from pathlib import Path
from typing import Optional, List, Tuple

from . import config


def project_root() -> str:
    return config.project_root()


def _backup_dir() -> str:
    return os.path.join(project_root(), ".swarm", "backups")


def ensure_swarm_dirs() -> None:
    os.makedirs(_backup_dir(), exist_ok=True)


def resolve_and_validate_path(path: str, allow_external: bool = False) -> str:
    """Resolve `path` and validate it is inside PROJECT_ROOT unless allow_external."""
    root = project_root()
    p = Path(path)
    if p.is_absolute():
        resolved = str(p.resolve())
    else:
        rel = path.lstrip("/\\")
        resolved = str((Path(root) / rel).resolve())

    if not allow_external:
        root_real = os.path.normcase(os.path.realpath(root))
        target = os.path.normcase(resolved)
        if target != root_real and not target.startswith(root_real + os.sep):
            raise ValueError(f"Acceso denegado: '{path}' está fuera de la raíz del proyecto.")
    return resolved


def _backup_bucket(resolved_path: str) -> str:
    """A collision-resistant, escape-proof directory for a file's backups.

    Instead of mangling the relative path (which was fragile against traversal),
    we hash the absolute path and keep a human hint in the folder name.
    """
    digest = hashlib.sha1(os.path.normcase(resolved_path).encode("utf-8")).hexdigest()[:16]
    hint = os.path.basename(resolved_path)[:40].replace(os.sep, "_")
    return os.path.join(_backup_dir(), f"{hint}.{digest}")


def backup_file(resolved_path: str) -> Optional[str]:
    if not os.path.exists(resolved_path) or os.path.isdir(resolved_path):
        return None
    ensure_swarm_dirs()
    bucket = _backup_bucket(resolved_path)
    os.makedirs(bucket, exist_ok=True)
    timestamp = int(time.time() * 1000)
    backup_path = os.path.join(bucket, f"{timestamp}.bak")
    # Guarantee a unique timestamp/filename even when two backups land in the same
    # millisecond — otherwise a restore made within the same ms as the original
    # backup would overwrite that backup before copying it back (bug: restored the
    # wrong version). Bump by 1ms until free.
    while os.path.exists(backup_path):
        timestamp += 1
        backup_path = os.path.join(bucket, f"{timestamp}.bak")
    try:
        shutil.copy2(resolved_path, backup_path)
        return backup_path
    except Exception:
        return None


def get_diff(old_content: str, new_content: str, filename: str = "file") -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}")
    return "".join(diff)


def write_file_safe(path: str, content: str, overwrite_external: bool = False) -> Tuple[str, str, Optional[str]]:
    try:
        resolved = resolve_and_validate_path(path, allow_external=False)
    except ValueError:
        if overwrite_external:
            resolved = resolve_and_validate_path(path, allow_external=True)
        else:
            raise

    old_content = ""
    backup_p = None
    if os.path.exists(resolved):
        if os.path.isdir(resolved):
            raise IsADirectoryError(f"'{path}' es un directorio, no se puede escribir.")
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                old_content = f.read()
            backup_p = backup_file(resolved)
        except Exception:
            pass

    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)

    diff_out = get_diff(old_content, content, os.path.basename(resolved))
    return resolved, diff_out, backup_p


def delete_file_safe(path: str, confirmed_external: bool = False) -> Tuple[str, bool]:
    try:
        resolved = resolve_and_validate_path(path, allow_external=False)
    except ValueError:
        if confirmed_external:
            resolved = resolve_and_validate_path(path, allow_external=True)
        else:
            raise

    if not os.path.exists(resolved):
        raise FileNotFoundError(f"'{path}' no existe.")

    if os.path.isfile(resolved):
        backup_file(resolved)
        os.remove(resolved)
        return resolved, False
    for root, _dirs, files in os.walk(resolved):
        for file in files:
            backup_file(os.path.join(root, file))
    shutil.rmtree(resolved)
    return resolved, True


def list_backups(path: str) -> List[Tuple[str, int]]:
    resolved = resolve_and_validate_path(path, allow_external=True)
    bucket = _backup_bucket(resolved)
    if not os.path.exists(bucket):
        return []
    backups = []
    for file in os.listdir(bucket):
        if file.endswith(".bak"):
            try:
                ts = int(file.split(".")[0])
                backups.append((os.path.join(bucket, file), ts))
            except ValueError:
                continue
    backups.sort(key=lambda x: x[1], reverse=True)
    return backups


def restore_backup(path: str, timestamp: int) -> str:
    resolved = resolve_and_validate_path(path, allow_external=True)
    for bp, ts in list_backups(path):
        if ts == timestamp:
            backup_file(resolved)
            os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
            shutil.copy2(bp, resolved)
            return resolved
    raise FileNotFoundError(f"No se encontró backup con timestamp {timestamp} para '{path}'.")
