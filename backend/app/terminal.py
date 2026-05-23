"""
WebSocket-based interactive terminal.
Runs a shell subprocess, pipes stdin/stdout over the WebSocket.
Handles `cd` built-in to maintain CWD state across commands.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_IS_WIN = sys.platform == "win32"


def _prompt(cwd: Path) -> str:
    """Colored prompt: ~/path ❯"""
    p = str(cwd)
    home = str(Path.home())
    if p.startswith(home):
        p = "~" + p[len(home):]
    # cyan path + green chevron
    return f"\x1b[36m{p}\x1b[0m \x1b[32m❯\x1b[0m "


async def _run_cmd(cmd: str, cwd: Path, ws: WebSocket) -> None:
    """Execute one command and stream its output to the WebSocket."""
    try:
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}

        if _IS_WIN:
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-Command", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
                env=env,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
                env=env,
                executable="/bin/bash",
            )

        assert proc.stdout
        while True:
            chunk = await proc.stdout.read(2048)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\n", "\r\n")
            await ws.send_text(text)

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            await ws.send_text(f"\x1b[2m[exit {proc.returncode}]\x1b[0m\r\n")

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await ws.send_text(f"\x1b[31mError: {exc}\x1b[0m\r\n")


async def handle_terminal_ws(websocket: WebSocket, initial_cwd: str) -> None:
    """
    Main WebSocket handler for the integrated terminal.

    Protocol (JSON over text frames):
      client → server: {"type": "command", "cmd": "npm run dev"}
      client → server: {"type": "interrupt"}
      server → client: plain text (terminal output, ANSI escape codes)
    """
    await websocket.accept()
    logger.info("Terminal session started cwd=%s", initial_cwd)

    try:
        cwd = Path(initial_cwd).resolve()
    except Exception:
        cwd = Path.home()

    # Send a welcome prompt
    await websocket.send_text(_prompt(cwd))

    current_proc: asyncio.subprocess.Process | None = None

    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            break
        except Exception:
            break

        try:
            msg = json.loads(raw)
        except Exception:
            continue

        mtype = msg.get("type")

        if mtype == "interrupt":
            if current_proc and current_proc.returncode is None:
                try:
                    current_proc.kill()
                except Exception:
                    pass
            await websocket.send_text("^C\r\n" + _prompt(cwd))
            continue

        if mtype != "command":
            continue

        cmd = msg.get("cmd", "").strip()
        if not cmd:
            await websocket.send_text(_prompt(cwd))
            continue

        # Built-ins: cd, clear/cls, pwd
        if cmd == "pwd":
            await websocket.send_text(str(cwd) + "\r\n" + _prompt(cwd))
            continue

        if cmd in ("clear", "cls"):
            await websocket.send_text("\x1b[2J\x1b[H" + _prompt(cwd))
            continue

        if cmd.startswith("cd"):
            target = cmd[2:].strip().strip('"\'')
            if not target or target == "~":
                new_cwd = Path.home()
            else:
                new_cwd = (cwd / target).resolve() if not Path(target).is_absolute() else Path(target)
            if new_cwd.is_dir():
                cwd = new_cwd
                await websocket.send_text(_prompt(cwd))
            else:
                await websocket.send_text(f"\x1b[31mcd: {target}: No such directory\x1b[0m\r\n{_prompt(cwd)}")
            continue

        # Regular command
        await _run_cmd(cmd, cwd, websocket)
        await websocket.send_text(_prompt(cwd))

    logger.info("Terminal session ended")
