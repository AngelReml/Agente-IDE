import os
import shutil
import time
import difflib
from pathlib import Path
from typing import Optional, List, Tuple

# We'll read the PROJECT_ROOT dynamically at import or use the default
PROJECT_ROOT: str = os.getenv(
    "PROJECT_ROOT",
    str(Path.home() / "swarm-projects" / "current"),
)

SWARM_DIR = os.path.join(PROJECT_ROOT, ".swarm")
BACKUP_DIR = os.path.join(SWARM_DIR, "backups")

def ensure_swarm_dirs() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)

def resolve_and_validate_path(path: str, allow_external: bool = False) -> str:
    """Resolve path and validate it is inside PROJECT_ROOT.
    If allow_external is True, we allow paths outside project, but we resolve them fully.
    """
    p = Path(path)
    if p.is_absolute():
        resolved = str(p.resolve())
    else:
        rel = path.lstrip("/\\")
        resolved = str((Path(PROJECT_ROOT) / rel).resolve())
    
    if not allow_external:
        root = os.path.normcase(os.path.realpath(PROJECT_ROOT))
        target = os.path.normcase(resolved)
        # Check target is inside or is root itself
        if target != root and not target.startswith(root + os.sep):
            raise ValueError(f"Acceso denegado: el archivo '{path}' está fuera de la raíz del proyecto.")
            
    return resolved

def get_relative_to_root(resolved_path: str) -> str:
    """Return a path relative to PROJECT_ROOT, escaping characters that are bad for filesystem."""
    try:
        return os.path.relpath(resolved_path, PROJECT_ROOT)
    except ValueError:
        # For paths on other drives on Windows
        return os.path.splitdrive(resolved_path)[1].lstrip("/\\")

def backup_file(resolved_path: str) -> Optional[str]:
    """Creates a timestamped backup of the resolved file.
    Returns the path to the backup file, or None if the file didn't exist or couldn't be backed up.
    """
    if not os.path.exists(resolved_path) or os.path.isdir(resolved_path):
        return None
        
    ensure_swarm_dirs()
    rel_path = get_relative_to_root(resolved_path)
    # Sanitize path to prevent backup folder escape
    safe_rel_path = rel_path.replace("..", "_up_").replace(":", "_drive_")
    
    file_backup_dir = os.path.join(BACKUP_DIR, safe_rel_path)
    os.makedirs(file_backup_dir, exist_ok=True)
    
    timestamp = int(time.time() * 1000)
    backup_filename = f"{timestamp}.bak"
    backup_path = os.path.join(file_backup_dir, backup_filename)
    
    try:
        shutil.copy2(resolved_path, backup_path)
        return backup_path
    except Exception:
        return None

def get_diff(old_content: str, new_content: str, filename: str = "file") -> str:
    """Generates unified diff between old and new contents."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}"
    )
    return "".join(diff)

def write_file_safe(path: str, content: str, overwrite_external: bool = False) -> Tuple[str, str, Optional[str]]:
    """Writes a file safely:
    1. Validates path.
    2. Backs up existing file.
    3. Writes the content.
    Returns (resolved_path, diff_output, backup_path).
    """
    # 1. Path validation
    is_external = False
    try:
        resolved = resolve_and_validate_path(path, allow_external=False)
    except ValueError:
        if overwrite_external:
            resolved = resolve_and_validate_path(path, allow_external=True)
            is_external = True
        else:
            raise
            
    # 2. Read old content to generate diff and backup
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
            pass # Continue writing even if backup fails, but log it if possible
            
    # 3. Ensure parent directory exists
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    
    # 4. Write new content
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)
        
    diff_out = get_diff(old_content, content, os.path.basename(resolved))
    return resolved, diff_out, backup_p

def delete_file_safe(path: str, confirmed_external: bool = False) -> Tuple[str, bool]:
    """Deletes a file safely by backing it up first, then removing it.
    Returns (resolved_path, was_directory).
    """
    is_external = False
    try:
        resolved = resolve_and_validate_path(path, allow_external=False)
    except ValueError:
        if confirmed_external:
            resolved = resolve_and_validate_path(path, allow_external=True)
            is_external = True
        else:
            raise
            
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"'{path}' no existe.")
        
    # Backup before delete
    if os.path.isfile(resolved):
        backup_file(resolved)
        os.remove(resolved)
        return resolved, False
    else:
        # Directory delete. Let's backup all files in it recursively
        for root, dirs, files in os.walk(resolved):
            for file in files:
                file_path = os.path.join(root, file)
                backup_file(file_path)
        shutil.rmtree(resolved)
        return resolved, True

def list_backups(path: str) -> List[Tuple[str, int]]:
    """List all backups for a given file. Returns a list of (backup_path, timestamp)."""
    resolved = resolve_and_validate_path(path, allow_external=True)
    rel_path = get_relative_to_root(resolved)
    safe_rel_path = rel_path.replace("..", "_up_").replace(":", "_drive_")
    
    file_backup_dir = os.path.join(BACKUP_DIR, safe_rel_path)
    if not os.path.exists(file_backup_dir):
        return []
        
    backups = []
    for file in os.listdir(file_backup_dir):
        if file.endswith(".bak"):
            backup_path = os.path.join(file_backup_dir, file)
            try:
                timestamp = int(file.split(".")[0])
                backups.append((backup_path, timestamp))
            except ValueError:
                continue
                
    # Sort by timestamp descending (newest first)
    backups.sort(key=lambda x: x[1], reverse=True)
    return backups

def restore_backup(path: str, timestamp: int) -> str:
    """Restores a backup for a file by timestamp."""
    resolved = resolve_and_validate_path(path, allow_external=True)
    backups = list_backups(path)
    target_backup = None
    for bp, ts in backups:
        if ts == timestamp:
            target_backup = bp
            break
            
    if not target_backup:
        raise FileNotFoundError(f"No se encontró un backup con timestamp {timestamp} para '{path}'.")
        
    # Backup current state before restoring
    backup_file(resolved)
    
    # Restore
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    shutil.copy2(target_backup, resolved)
    return resolved
