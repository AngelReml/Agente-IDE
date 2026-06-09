"""Tests for the phase-completion work: sandbox hardening, job queue, tenancy,
retrieval, orchestrator gate/budget, checkpoints, depgraph, background, metrics."""
import asyncio

from app.platform import sandbox
from app import queue as jobqueue
from app import tenancy, retrieval, orchestrator, checkpoints, depgraph, background, metrics


# ── Fase 1: sandbox hardening (pure argv) ───────────────────────────────────────

def test_docker_args_are_hardened(monkeypatch):
    monkeypatch.delenv("SWARM_SANDBOX_NETWORK", raising=False)
    args = sandbox.DockerBackend().build_args(["python", "-c", "print(1)"], "/work/ws")
    joined = " ".join(args)
    assert "--cap-drop ALL" in joined
    assert "--network none" in joined            # default: no egress
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in joined
    assert "--user 1000:1000" in joined
    assert "/work/ws:/workspace" in joined
    assert args[-3:] == ["python", "-c", "print(1)"]  # command appended last


def test_docker_runtime_flag_is_opt_in(monkeypatch):
    # Default: no --runtime (plain runc), unchanged behaviour.
    monkeypatch.delenv("SWARM_SANDBOX_RUNTIME", raising=False)
    args = sandbox.DockerBackend().build_args(["sh", "-c", "echo hi"], "/work/ws")
    assert "--runtime" not in args

    # Flag set → hardened runtime injected right after `docker run --rm`.
    monkeypatch.setenv("SWARM_SANDBOX_RUNTIME", "runsc")
    args = sandbox.DockerBackend().build_args(["sh", "-c", "echo hi"], "/work/ws")
    i = args.index("--runtime")
    assert args[i + 1] == "runsc"
    assert args[:i] == ["docker", "run", "--rm"]   # before the rest of the hardening


def test_docker_available_uses_version_not_info(monkeypatch):
    # `docker info` is denied by a socket-proxy allowlist; `docker version` (/version)
    # is allowed. Ensure preflight probes with `version` so it works behind the proxy.
    sandbox.docker_available.cache_clear()
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")
    calls = []

    class _R:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert sandbox.docker_available() is True
    sandbox.docker_available.cache_clear()
    assert calls and calls[0][:2] == ["docker", "version"]


def test_preflight_local_unaffected(monkeypatch):
    monkeypatch.setenv("SWARM_SANDBOX", "local")
    ok, msg = sandbox.preflight()
    assert ok and msg == "sandbox=local"


def _fake_proc(returncode=0, stderr=b""):
    class _R:
        pass
    r = _R()
    r.returncode = returncode
    r.stderr = stderr
    r.stdout = b""
    return r


def test_preflight_validates_runtime_ok(monkeypatch):
    monkeypatch.setenv("SWARM_SANDBOX", "docker")
    monkeypatch.setenv("SWARM_SANDBOX_RUNTIME", "runsc")
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    # image inspect → ok, runtime smoke run → ok
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: _fake_proc(0))
    ok, msg = sandbox.preflight()
    assert ok and "runtime=runsc" in msg


def test_preflight_fails_when_runtime_missing(monkeypatch):
    monkeypatch.setenv("SWARM_SANDBOX", "docker")
    monkeypatch.setenv("SWARM_SANDBOX_RUNTIME", "runsc")
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)

    def fake_run(args, **k):
        # image inspect passes; the runtime smoke run fails clearly.
        if args[:3] == ["docker", "image", "inspect"]:
            return _fake_proc(0)
        return _fake_proc(125, b"unknown runtime specified runsc")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    ok, msg = sandbox.preflight()
    assert not ok and "runsc" in msg and "no disponible" in msg


def test_sandbox_resource_limits_default_matches_config(monkeypatch):
    # Default limits reproduce the historic hardcoded quota exactly (no regression).
    for v in ("SWARM_SANDBOX_CPUS", "SWARM_SANDBOX_PIDS", "SWARM_SANDBOX_MEMORY"):
        monkeypatch.delenv(v, raising=False)
    args = sandbox.DockerBackend().build_args(["sh"], "/ws")
    joined = " ".join(args)
    assert "--memory 1g" in joined and "--pids-limit 256" in joined and "--cpus 2" in joined


def test_sandbox_per_workspace_limits_override(monkeypatch):
    # An explicit ResourceLimits (e.g. from tenancy.limits_for) wins over config.
    limits = sandbox.ResourceLimits(cpus="0.5", memory="512m", pids="64")
    args = sandbox.DockerBackend().build_args(["sh"], "/ws", limits=limits)
    joined = " ".join(args)
    assert "--cpus 0.5" in joined and "--memory 512m" in joined and "--pids-limit 64" in joined


# ── Fase 2: in-process job queue ────────────────────────────────────────────────

def test_inprocess_queue_runs_job():
    async def scenario():
        q = jobqueue.InProcessQueue()
        jid = await q.submit("calc", lambda: _async_return(42))
        job = await q.join(jid)
        return job

    job = asyncio.run(scenario())
    assert job.status == "done" and job.result == 42


async def _async_return(v):
    return v


# ── Fase 3: tenancy ─────────────────────────────────────────────────────────────

def test_tenancy_users_workspaces_roles(tmp_path):
    db = tenancy.TenancyDB(str(tmp_path / "t.db"))
    owner = db.create_user("alice")
    member = db.create_user("bob")
    ws = db.create_workspace("proj", str(tmp_path / "proj"), owner, budget_usd=1.0)
    assert db.role_of(owner, ws) == "owner"
    db.add_member(member, ws, "editor")
    assert db.role_of(member, ws) == "editor"
    assert any(w["id"] == ws for w in db.workspaces_for(member))


def test_tenancy_resource_limits(tmp_path):
    db = tenancy.TenancyDB(str(tmp_path / "t.db"))
    owner = db.create_user("alice")
    # Workspace with a custom cpu/pid cap but no memory override.
    ws = db.create_workspace("p", str(tmp_path), owner, limits={"cpus": "1", "pids": "64"})
    lim = db.limits_for(ws)
    assert lim.cpus == "1" and lim.pids == "64"
    assert lim.memory == "1g"          # NULL column → config default
    # Unknown workspace → all config defaults.
    base = db.limits_for("ghost")
    assert base.cpus == "2" and base.memory == "1g" and base.pids == "256"


def test_tenancy_limits_for_root(tmp_path):
    db = tenancy.TenancyDB(str(tmp_path / "t.db"))
    owner = db.create_user("alice")
    ws_root = str(tmp_path / "proj")
    db.create_workspace("p", ws_root, owner, limits={"cpus": "0.5", "memory": "256m"})
    # Active PROJECT_ROOT matching a workspace root → that workspace's caps.
    lim = db.limits_for_root(ws_root)
    assert lim.cpus == "0.5" and lim.memory == "256m" and lim.pids == "256"
    # A root owned by no workspace → process/config defaults (local single-user path).
    other = db.limits_for_root(str(tmp_path / "elsewhere"))
    assert other.cpus == "2" and other.memory == "1g"


def test_local_backend_ignores_limits(tmp_path):
    import sys
    # LocalBackend accepts limits for a uniform interface but must run regardless.
    lim = sandbox.ResourceLimits(cpus="0.1", memory="64m", pids="8")
    res = sandbox.LocalBackend().run([sys.executable, "-c", "print('ok')"],
                                     cwd=str(tmp_path), timeout=30, limits=lim)
    assert res.returncode == 0 and "ok" in res.stdout


def test_tenancy_budget(tmp_path):
    db = tenancy.TenancyDB(str(tmp_path / "t.db"))
    owner = db.create_user("alice")
    ws = db.create_workspace("p", str(tmp_path), owner, budget_usd=1.0)
    db.record_usage(ws, 0.4, 100, 50)
    assert db.check_budget(ws)["ok"]
    db.record_usage(ws, 0.8, 100, 50)
    assert not db.check_budget(ws)["ok"]


def test_workspace_path_confinement(tmp_path):
    root = str(tmp_path)
    assert tenancy.resolve_in_workspace(root, "sub/file.py").startswith(root)
    import pytest
    with pytest.raises(ValueError):
        tenancy.resolve_in_workspace(root, "../../etc/passwd")


def test_tenancy_audit(tmp_path):
    db = tenancy.TenancyDB(str(tmp_path / "t.db"))
    u = db.create_user("a")
    ws = db.create_workspace("p", str(tmp_path), u)
    db.audit(u, ws, "write_file", "main.py")
    log = db.audit_log(ws)
    assert log and log[0]["action"] == "write_file"


# ── Fase 4: retrieval + gate/budget helpers ─────────────────────────────────────

def test_tokenize_splits_identifiers():
    toks = set(retrieval.tokenize("getUserName user_id"))
    assert {"user", "name", "id"} <= toks


def test_tfidf_ranks_relevant_chunk_first():
    r = retrieval.TfidfRetriever()
    r.add("auth.py", "def login(user, password):\n    return verify_password(user, password)")
    r.add("math.py", "def add(a, b):\n    return a + b")
    hits = r.query("password login", k=2)
    assert hits and hits[0].path == "auth.py"


def test_review_gate_helpers():
    assert orchestrator.review_rejected("❌ RECHAZADO: SQL injection")
    assert orchestrator.review_rejected("rechazado por seguridad")
    assert not orchestrator.review_rejected("✅ APROBADO: ok")


def test_budget_helper():
    assert not orchestrator.budget_exceeded(0.5, 1.0)
    assert orchestrator.budget_exceeded(1.0, 1.0)
    assert not orchestrator.budget_exceeded(99.0, 0)  # 0 = unlimited


# ── Fase 5: checkpoints, depgraph, background ───────────────────────────────────

def test_checkpoint_snapshot_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / "app.py").write_text("v1")
    cp = checkpoints.create_checkpoint("antes")
    assert "app.py" in cp["files"]
    (tmp_path / "app.py").write_text("v2-roto")
    res = checkpoints.restore_checkpoint(cp["id"])
    assert res["restored"] == 1
    assert (tmp_path / "app.py").read_text() == "v1"


def test_depgraph_parse_imports():
    py = depgraph.parse_imports("m.py", "from a.b import c\nimport d\nimport os")
    assert "a.b" in py and "d" in py and "os" in py
    js = depgraph.parse_imports("c.tsx", "import X from './y'\nconst z = require('lib')")
    assert "./y" in js and "lib" in js


def test_depgraph_dependents():
    g = {"a.py": ["lib.util"], "b.py": ["os"], "c.py": ["lib.util", "x"]}
    assert depgraph.dependents_of(g, "lib.util") == ["a.py", "c.py"]


def test_background_registry():
    reg = background.BackgroundRegistry()
    tid = reg.register("triage", "revisa issues", "interval:10")
    assert reg.get(tid).name == "triage"
    assert len(reg.list()) == 1
    # never run → due
    assert any(t.id == tid for t in reg.due())
    reg.mark_run(tid)
    assert not any(t.id == tid for t in reg.due())  # just ran → not due
    assert reg.set_enabled(tid, False) and reg.remove(tid)


# ── Fase 6: metrics ─────────────────────────────────────────────────────────────

def test_metrics_render():
    m = metrics.Metrics()
    m.inc("swarm_runs_total", mode="swarm")
    m.inc("swarm_runs_total", mode="swarm")
    m.set_gauge("swarm_active_runs", 3)
    out = m.render()
    assert 'swarm_runs_total{mode="swarm"} 2.0' in out
    assert "swarm_active_runs 3" in out
    assert m.value("swarm_runs_total", mode="swarm") == 2.0


def test_request_id_unique():
    assert metrics.new_request_id() != metrics.new_request_id()
