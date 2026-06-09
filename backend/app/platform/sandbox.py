"""
Execution sandbox (Fase 1).

Abstracts *where* the agent's commands run. `LocalBackend` keeps v4.0 behaviour
(host subprocess, fine for local single-user). `DockerBackend` runs each command
inside a throwaway container with the workspace mounted, no host FS reach and a
locked-down network — the prerequisite for any shared/exposed deployment.

`get_backend()` selects via SWARM_SANDBOX = local | docker | auto. Everything
degrades to LocalBackend when Docker is unavailable, so nothing breaks locally.
"""
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from .. import config


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ResourceLimits:
    """Per-sandbox resource quota (CPU/mem/pids). Defaults come from config; the
    multi-tenant path overrides them per workspace via `tenancy.limits_for()`."""
    cpus: str
    memory: str
    pids: str

    @classmethod
    def from_config(cls) -> "ResourceLimits":
        return cls(cpus=config.sandbox_cpus(), memory=config.sandbox_memory(),
                   pids=config.sandbox_pids())


class LocalBackend:
    name = "local"

    def run(self, args: list[str], cwd: str, timeout: int, env: dict | None = None,
            limits: "ResourceLimits | None" = None) -> ExecResult:
        # `limits` is accepted for a uniform backend interface but ignored: a host
        # subprocess has no cgroup quota. Resource caps only apply to DockerBackend.
        exe = shutil.which(args[0]) or shutil.which(os.path.basename(args[0]))
        if exe:
            args = [exe] + args[1:]
        else:
            return ExecResult(127, "", f"Ejecutable '{args[0]}' no encontrado en PATH.")
        full_env = {**os.environ, "CI": "true", "TERM": "dumb", "PYTHONUNBUFFERED": "1", **(env or {})}
        try:
            r = subprocess.run(args, shell=False, cwd=cwd, capture_output=True, text=True,
                               timeout=timeout, env=full_env)
            return ExecResult(r.returncode, r.stdout or "", r.stderr or "")
        except subprocess.TimeoutExpired:
            return ExecResult(124, "", f"Timeout después de {timeout}s.")
        except Exception as e:  # pragma: no cover
            return ExecResult(1, "", f"Error de ejecución: {e}")


class DockerBackend:
    name = "docker"

    def build_args(self, args: list[str], cwd: str, env: dict | None = None,
                   limits: "ResourceLimits | None" = None) -> list[str]:
        """Pure construction of the `docker run` argv (unit-tested for hardening)."""
        limits = limits or ResourceLimits.from_config()
        docker_args = ["docker", "run", "--rm"]
        runtime = config.sandbox_runtime()
        if runtime:
            # Hardened runtime (gVisor 'runsc', Kata…) for stronger isolation.
            docker_args += ["--runtime", runtime]
        docker_args += [
            "--network", config.sandbox_network(),   # 'none' by default → no egress
            "--memory", limits.memory,
            "--pids-limit", limits.pids,
            "--cpus", limits.cpus,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",                            # rootfs read-only; only /workspace is writable
            "--tmpfs", "/tmp:rw,size=256m",
            "--user", "1000:1000",                    # never root inside the sandbox
            "-v", f"{cwd}:/workspace",
            "-w", "/workspace",
            "-e", "CI=true", "-e", "PYTHONUNBUFFERED=1",
        ]
        for k, v in (env or {}).items():
            docker_args += ["-e", f"{k}={v}"]
        docker_args.append(config.sandbox_image())
        docker_args += args  # original command name; resolved inside the image
        return docker_args

    def run(self, args: list[str], cwd: str, timeout: int, env: dict | None = None,
            limits: "ResourceLimits | None" = None) -> ExecResult:
        docker_args = self.build_args(args, cwd, env, limits)
        try:
            r = subprocess.run(docker_args, shell=False, capture_output=True, text=True, timeout=timeout)
            return ExecResult(r.returncode, r.stdout or "", r.stderr or "")
        except subprocess.TimeoutExpired:
            return ExecResult(124, "", f"Timeout después de {timeout}s (sandbox docker).")
        except Exception as e:  # pragma: no cover
            return ExecResult(1, "", f"Error de sandbox docker: {e}")


def preflight() -> tuple[bool, str]:
    """Check the configured sandbox can run. Used at startup / health."""
    mode = config.sandbox_mode()
    if mode == "local":
        return True, "sandbox=local"
    if not docker_available():
        return (mode != "docker"), f"sandbox={mode}: docker no disponible" + (
            " → fallback local" if mode == "auto" else " (requerido)")
    img = config.sandbox_image()
    try:
        r = subprocess.run(["docker", "image", "inspect", img], capture_output=True, timeout=10)
        if r.returncode != 0:
            return False, f"sandbox=docker: imagen '{img}' no encontrada (make sandbox-image)"
    except Exception as e:  # pragma: no cover
        return False, f"sandbox=docker: error {e}"
    via = f" via {config.docker_host()}" if config.docker_host() else ""
    rt = f" runtime={config.sandbox_runtime()}" if config.sandbox_runtime() else ""
    return True, f"sandbox=docker img={img}{rt}{via}"


@lru_cache(maxsize=1)
def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        # `docker version` hits /version, which a socket-proxy allows by default
        # (unlike `docker info`); returns non-zero if the daemon is unreachable.
        r = subprocess.run(["docker", "version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def get_backend():
    mode = config.sandbox_mode()
    if mode == "docker":
        return DockerBackend()
    if mode == "auto":
        return DockerBackend() if docker_available() else LocalBackend()
    return LocalBackend()
