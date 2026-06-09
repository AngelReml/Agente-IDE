"""
Workspace-wide checkpoints / time-travel (Fase 5).

v4.0 backed up individual files; here we snapshot the *whole* workspace so the
user can revert an entire agent run, not just one file. Snapshots live under
.swarm/checkpoints/<id>/ with a manifest. Restore copies files back (current
state is itself snapshot-able beforehand by the caller).
"""
import json
import os
import shutil
import time

from . import config

_MAX_FILE = 1_000_000


def _dir() -> str:
    return os.path.join(config.project_root(), ".swarm", "checkpoints")


def create_checkpoint(label: str = "") -> dict:
    root = config.project_root()
    ckpt_id = int(time.time() * 1000)
    dest = os.path.join(_dir(), str(ckpt_id))
    files: list[str] = []
    for dp, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
        for fname in fnames:
            full = os.path.join(dp, fname)
            rel = os.path.relpath(full, root)
            try:
                if config.is_secret_path(full):
                    continue  # never snapshot .env / keys / credentials in cleartext
                if os.path.getsize(full) > _MAX_FILE:
                    continue
                out = os.path.join(dest, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(full, out)
                files.append(rel)
            except OSError:
                continue
    manifest = {"id": ckpt_id, "label": label, "created_at": ckpt_id, "files": files}
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return manifest


def list_checkpoints() -> list[dict]:
    d = _dir()
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d), reverse=True):
        mf = os.path.join(d, name, "manifest.json")
        if os.path.isfile(mf):
            try:
                out.append(json.load(open(mf, encoding="utf-8")))
            except Exception:
                continue
    return out


def restore_checkpoint(ckpt_id: int, prune: bool = False) -> dict:
    """Restore the snapshot. With prune=True it also DELETES files created after the
    checkpoint (a true rollback), used by the swarm review gate to undo rejected work."""
    root = config.project_root()
    src = os.path.join(_dir(), str(ckpt_id))
    mf = os.path.join(src, "manifest.json")
    if not os.path.isfile(mf):
        raise FileNotFoundError(f"Checkpoint {ckpt_id} no encontrado")
    manifest = json.load(open(mf, encoding="utf-8"))
    root_real = os.path.realpath(root)
    restored: list[str] = []
    for rel in manifest["files"]:
        s = os.path.join(src, rel)
        d = os.path.join(root, rel)
        # Guard against a tampered manifest with '..' escaping the workspace.
        try:
            if os.path.commonpath([root_real, os.path.realpath(d)]) != root_real:
                continue
        except ValueError:
            continue
        if os.path.isfile(s):
            os.makedirs(os.path.dirname(d) or ".", exist_ok=True)
            shutil.copy2(s, d)
            restored.append(rel)

    pruned = 0
    if prune:
        snapshot = set(manifest["files"])
        for dp, dirs, fnames in os.walk(root):
            dirs[:] = [d for d in dirs if d not in config.SKIP_DIRS]
            for fname in fnames:
                full = os.path.join(dp, fname)
                rel = os.path.relpath(full, root)
                if rel in snapshot or config.is_secret_path(full):
                    continue
                try:
                    os.remove(full)  # created after the checkpoint → remove to complete rollback
                    pruned += 1
                except OSError:
                    continue
    return {"id": ckpt_id, "restored": len(restored), "pruned": pruned, "files": restored}
