"""Cost pricing, loop detection, store, diff stats, safe_fs."""
import os

from app import cost_tracker, runtime, store, diff_parser, safe_fs


# ── Cost pricing (B2 regression: gemini 2.5 was billed at $0) ───────────────────

def test_gemini_25_is_priced():
    assert cost_tracker.price("gemini", "gemini-2.5-flash") != (0.0, 0.0)
    assert cost_tracker.price("gemini", "gemini-2.5-pro") != (0.0, 0.0)


def test_cost_of_math():
    # opus: 15 in / 75 out per 1M
    c = cost_tracker.cost_of("anthropic", "claude-opus-4-5", 1_000_000, 1_000_000)
    assert round(c, 2) == 90.0


def test_unknown_model_is_free():
    assert cost_tracker.cost_of("huggingface", "whatever", 1000, 1000) == 0.0


def test_record_accumulates_session():
    before = cost_tracker.session_stats()["input_tokens"]
    cost_tracker.record("anthropic", "claude-haiku-4-5", 100, 50)
    after = cost_tracker.session_stats()["input_tokens"]
    assert after == before + 100


# ── Loop detector (B1 regression: alternating A,B,A,B must be detectable) ────────

def test_loop_detector_counts_repeats():
    d = runtime.LoopDetector(window=8)
    for _ in range(5):
        n = d.check("read_file", {"path": "x"})
    assert n == 5


def test_loop_detector_window_is_sliding():
    d = runtime.LoopDetector(window=3)
    d.check("a", {}); d.check("b", {}); d.check("c", {})
    # 'a' fell out of the 3-wide window
    assert d.check("a", {}) == 1


def test_alternating_pattern_tracked():
    d = runtime.LoopDetector(window=8)
    last = 0
    for _ in range(4):
        d.check("A", {"i": 1})
        last = d.check("B", {"i": 2})
    assert last >= 3  # B seen repeatedly within the window


# ── Store ────────────────────────────────────────────────────────────────────

def test_store_run_lifecycle():
    store.init()
    rid = "testrun123"
    store.start_run(rid, "sess1", "do a thing")
    store.record_event(rid, "tool_start", "write_file x", "write_file")
    store.finish_run(rid, "done", "anthropic", "claude-opus-4-5",
                     {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.1})
    runs = store.list_runs("sess1")
    assert any(r["id"] == rid and r["status"] == "done" for r in runs)
    evs = store.get_run_events(rid)
    assert evs and evs[0]["tool"] == "write_file"


# ── Diff stats ───────────────────────────────────────────────────────────────

def test_parse_diff_stats():
    diff = "@@ -1,2 +1,3 @@\n+added line\n-removed line\n context\n+another add\n"
    s = diff_parser.parse_diff_stats(diff)
    assert s["lines_added"] == 2
    assert s["lines_removed"] == 1
    assert s["hunks"] == 1


# ── safe_fs path validation + backups ────────────────────────────────────────

def test_resolve_rejects_external_when_disallowed():
    import pytest
    with pytest.raises(ValueError):
        safe_fs.resolve_and_validate_path("/etc/passwd", allow_external=False)


def test_write_then_backup_then_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    safe_fs.write_file_safe("note.txt", "v1")
    safe_fs.write_file_safe("note.txt", "v2")  # creates a backup of v1
    backups = safe_fs.list_backups("note.txt")
    assert len(backups) >= 1
    ts = backups[-1][1]
    safe_fs.restore_backup("note.txt", ts)
    assert (tmp_path / "note.txt").read_text() == "v1"
