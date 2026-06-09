"""Phase 2 (architecture plan): per-session isolation of the State Guard
(modified-file tracking) and the chat history."""


def test_state_guard_isolated_by_session():
    from app import state_context
    state_context.set_session("guard-A")
    state_context.reset_session()
    state_context.add_modified_file("a.py")
    state_context.mark_changelog_added()
    assert "a.py" in state_context.get_modified_files()
    assert state_context.was_changelog_added()

    # A different session sees a clean slate, not A's mutations.
    state_context.set_session("guard-B")
    state_context.reset_session()
    assert state_context.get_modified_files() == set()
    assert not state_context.was_changelog_added()

    # Switching back to A preserves A's tracking.
    state_context.set_session("guard-A")
    assert "a.py" in state_context.get_modified_files()


def test_history_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from app import store
    store.save_history_raw([{"x": 1}], "hA")
    store.save_history_raw([{"y": 2}, {"y": 3}], "hB")
    assert store.load_history_raw("hA") == [{"x": 1}]
    assert len(store.load_history_raw("hB")) == 2
    # Clearing one session does not touch the other.
    store.clear_history("hA")
    assert store.load_history_raw("hA") == []
    assert len(store.load_history_raw("hB")) == 2


def test_graph_history_count_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from app import graph, store
    store.save_history_raw([], "gA")
    # session_message_count reads that session's history (lazy-loaded from store)
    assert graph.session_message_count("gA") == 0
    graph.clear_session_messages("gA")  # must not raise
    assert graph.session_message_count("gA") == 0
