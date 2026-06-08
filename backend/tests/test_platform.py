"""Tests for the v5.0 platform foundation: prompts, telemetry, auth, persistence,
sandbox, run manager, orchestrator scheduling, eval harness."""
import asyncio

import pytest

from app import prompts, telemetry, auth, persistence, runmanager, orchestrator
from app.platform import sandbox
from app.evals import harness


# ── Prompts / telemetry ─────────────────────────────────────────────────────────

def test_prompt_loads():
    p = prompts.load("system")
    assert "PLANIFICACIÓN" in p and "apply_patch" in p


def test_telemetry_span_is_noop_safe():
    with telemetry.span("unit", phase="test") as ctx:
        ctx["ok"] = True
    telemetry.event("done", n=1)  # must not raise


# ── Auth / RBAC ───────────────────────────────────────────────────────────────

def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv("SWARM_SECRET", "topsecret")
    tok = auth.issue_token("alice", "ws1", "editor")
    p = auth.verify_token(tok)
    assert p is not None and p.user_id == "alice" and p.role == "editor" and p.workspace == "ws1"


def test_token_tamper_rejected(monkeypatch):
    monkeypatch.setenv("SWARM_SECRET", "topsecret")
    tok = auth.issue_token("alice", role="owner")
    assert auth.verify_token(tok[:-2] + ("aa" if not tok.endswith("aa") else "bb")) is None


def test_token_expiry(monkeypatch):
    monkeypatch.setenv("SWARM_SECRET", "s")
    tok = auth.issue_token("bob", ttl_seconds=-1)
    assert auth.verify_token(tok) is None


def test_role_ordering():
    assert auth.Principal("u", "w", "owner").can("editor")
    assert auth.Principal("u", "w", "editor").can("viewer")
    assert not auth.Principal("u", "w", "viewer").can("editor")


# ── Persistence backend selection ───────────────────────────────────────────────

def test_persistence_defaults_to_sqlite():
    be = persistence.get_backend()
    assert be.name == "sqlite"
    be.init()
    be.start_run("r-plat", "s", "task")
    assert any(r["id"] == "r-plat" for r in be.list_runs("s"))


# ── Sandbox backend ─────────────────────────────────────────────────────────────

def test_sandbox_local_by_default():
    be = sandbox.get_backend()
    assert be.name == "local"


def test_local_backend_runs(tmp_path):
    res = sandbox.LocalBackend().run(["python3", "-c", "print('hola')"], cwd=str(tmp_path), timeout=30)
    assert res.returncode == 0 and "hola" in res.stdout


# ── Orchestrator: planner parsing + scheduling ──────────────────────────────────

def test_parse_plan():
    raw = '```json\n[{"id":"a","goal":"diseñar","role":"architect"},' \
          '{"id":"b","goal":"codear","role":"coder","depends_on":["a"]}]\n```'
    subs = orchestrator.parse_plan(raw)
    assert [s.id for s in subs] == ["a", "b"]
    assert subs[1].depends_on == ["a"] and subs[0].role == "architect"


def test_parse_plan_bad_role_defaults_coder():
    subs = orchestrator.parse_plan('[{"id":"x","goal":"g","role":"wizard"}]')
    assert subs[0].role == "coder"


def test_schedule_parallel_batches():
    subs = [
        orchestrator.SubTask("a", "g", "architect"),
        orchestrator.SubTask("b", "g", "coder", ["a"]),
        orchestrator.SubTask("c", "g", "coder", ["a"]),
        orchestrator.SubTask("d", "g", "reviewer", ["b", "c"]),
    ]
    batches = orchestrator.schedule(subs)
    ids = [[s.id for s in b] for b in batches]
    assert ids == [["a"], ["b", "c"], ["d"]]  # b and c run in parallel


def test_schedule_detects_cycle():
    subs = [orchestrator.SubTask("a", "g", "coder", ["b"]),
            orchestrator.SubTask("b", "g", "coder", ["a"])]
    with pytest.raises(ValueError):
        orchestrator.schedule(subs)


def test_schedule_unknown_dep():
    subs = [orchestrator.SubTask("a", "g", "coder", ["ghost"])]
    with pytest.raises(ValueError):
        orchestrator.schedule(subs)


# ── Run manager: durable + reconnect (replay) ───────────────────────────────────

def test_runmanager_replays_after_completion():
    async def fake_agent(task, session_id):
        for i in range(3):
            yield {"type": "token", "content": f"chunk{i}"}
        yield {"type": "done", "content": "ok"}

    async def scenario():
        mgr = runmanager.RunManager(fake_agent)
        rid = await mgr.start("t")
        await asyncio.sleep(0.05)  # let it finish
        return [ev async for ev in mgr.subscribe(rid)]

    events = asyncio.run(scenario())
    assert {"type": "done", "content": "ok"} in events
    assert sum(1 for e in events if e["type"] == "token") == 3


# ── Eval harness ─────────────────────────────────────────────────────────────

def test_harness_assertions(tmp_path):
    (tmp_path / "f.py").write_text("def sumar(a,b): return a+b\n")
    ok, _ = harness.assert_file_exists(str(tmp_path), "f.py")
    assert ok
    ok, _ = harness.assert_file_contains(str(tmp_path), "f.py", "def sumar")
    assert ok
    ok, _ = harness.assert_no_secret_leak(str(tmp_path), "todo bien, sin claves")
    assert ok
    bad, _ = harness.assert_no_secret_leak(str(tmp_path), "fuga sk-ant-123")
    assert not bad


def test_harness_run_task_with_mock():
    task = harness.EvalTask(
        id="mock", prompt="crea f.py",
        assertions=[(harness.assert_file_exists, "f.py")],
    )

    async def mock_agent(prompt, workspace):
        import os
        with open(os.path.join(workspace, "f.py"), "w") as fh:
            fh.write("ok")
        return "hecho"

    res = asyncio.run(harness.run_task(task, mock_agent))
    assert res.passed
