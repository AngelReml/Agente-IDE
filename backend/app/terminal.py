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

from . import security

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


async def _run_cmd(cmd: str, cwd: Path, ws: WebSocket, proc_holder: dict | None = None,
                   max_output: int = 2_000_000) -> None:
    """Execute one command and stream its output to the WebSocket.

    The spawned process is registered in `proc_holder["proc"]` so the handler's
    `interrupt` message can actually kill it (previously the handler never had a
    reference, so Ctrl+C was a no-op). Output is capped to avoid flooding the WS.
    """
    proc = None
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

        if proc_holder is not None:
            proc_holder["proc"] = proc

        assert proc.stdout
        sent = 0
        while True:
            chunk = await proc.stdout.read(2048)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\n", "\r\n")
            sent += len(text)
            if sent > max_output:
                await ws.send_text("\r\n\x1b[31m[salida truncada: demasiado larga]\x1b[0m\r\n")
                try:
                    proc.kill()
                except Exception:
                    pass
                break
            await ws.send_text(text)

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            await ws.send_text(f"\x1b[2m[exit {proc.returncode}]\x1b[0m\r\n")

    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        raise
    except Exception as exc:
        await ws.send_text(f"\x1b[31mError: {exc}\x1b[0m\r\n")
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None


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

    # The running command (if any) executes in a background task so the receive
    # loop stays responsive — that's what makes `interrupt` actually work. Its
    # process is shared via proc_holder so we can kill it.
    proc_holder: dict = {"proc": None}
    current_task: asyncio.Task | None = None

    async def _execute(command: str, run_cwd: Path) -> None:
        try:
            await _run_cmd(command, run_cwd, websocket, proc_holder)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        try:
            await websocket.send_text(_prompt(run_cwd))
        except Exception:
            pass

    try:
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
            busy = current_task is not None and not current_task.done()

            if mtype == "interrupt":
                proc = proc_holder.get("proc")
                if proc is not None and proc.returncode is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                else:
                    await websocket.send_text("^C\r\n" + _prompt(cwd))
                continue

            if mtype != "command":
                continue

            cmd = msg.get("cmd", "").strip()

            # Cheap built-ins are answered even while a command runs.
            if cmd == "pwd":
                await websocket.send_text(str(cwd) + "\r\n" + _prompt(cwd))
                continue
            if cmd in ("clear", "cls"):
                await websocket.send_text("\x1b[2J\x1b[H" + _prompt(cwd))
                continue

            if busy:
                await websocket.send_text(
                    "\x1b[33m[hay un comando en ejecución; usa Ctrl+C para interrumpir]\x1b[0m\r\n")
                continue

            if not cmd:
                await websocket.send_text(_prompt(cwd))
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

            # Defence-in-depth: block genuinely destructive commands even in the terminal.
            blocked = security.blocked_command(cmd)
            if blocked:
                await websocket.send_text(
                    f"\x1b[31mComando bloqueado por seguridad (patrón: {blocked})\x1b[0m\r\n{_prompt(cwd)}")
                continue

            # Run in the background so interrupt/pwd stay responsive.
            current_task = asyncio.create_task(_execute(cmd, cwd))
    finally:
        if current_task is not None and not current_task.done():
            current_task.cancel()

    logger.info("Terminal session ended")
