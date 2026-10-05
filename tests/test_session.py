"""Session persistence and analytics."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kite.memory.session import (
    Session,
    SessionMeta,
    create_session,
    format_meta_line,
    load_session,
    resolve_session_path,
)


def _c_test_append_meta_lifecycle_and_touch(kite_home, monkeypatch) -> None:
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hi"})
    path = session.path
    assert path is not None
    size_after_one = path.stat().st_size

    session.append({"role": "assistant", "content": "hello"})
    size_after_two = path.stat().st_size
    assert size_after_two > size_after_one

    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["type"] == "meta"
    assert sum(1 for ln in lines if '"type": "message"' in ln) == 2

    # updated_at refreshes on append
    meta = SessionMeta(
        id="test-id",
        created_at=time.time(),
        updated_at=1.0,
        cwd="/tmp",
        provider="p",
        model="m",
        task="t",
    )
    tracked = Session(meta=meta)
    tracked.save()
    before = json.loads(tracked.path.read_text(encoding="utf-8").splitlines()[0])["updated_at"]
    time.sleep(0.01)
    tracked.append({"role": "user", "content": "x"})
    after = json.loads(tracked.path.read_text(encoding="utf-8").splitlines()[0])["updated_at"]
    assert after > before

    # meta line length stays stable across timestamp patches
    stable = SessionMeta(
        id="x",
        created_at=1_700_000_000.0,
        updated_at=1_700_000_000.0,
        cwd="/tmp",
        provider="p",
        model="m",
        task="t",
    )
    first = format_meta_line(stable)
    stable.updated_at = 1_700_000_123.456789
    second = format_meta_line(stable)
    assert len(first) == len(second)

    # touch_meta must not read the whole session file
    touch = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    touch.append({"role": "user", "content": "hi"})
    touch_path = touch.path
    assert touch_path is not None
    original_read = Path.read_bytes

    def spy_read_bytes(self: Path) -> bytes:
        if self == touch_path:
            raise AssertionError("touch_meta should not read the whole session file")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    touch.append({"role": "assistant", "content": "hello"})


def _c_test_replace_and_load_resilience(kite_home) -> None:
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    for i in range(5):
        session.append({"role": "user", "content": f"turn {i}" * 50})
    path = session.path
    assert path is not None
    size_before = path.stat().st_size

    compacted = [
        {"role": "user", "content": "Previous conversation summary:\ncompacted"},
        {"role": "assistant", "content": "recent"},
    ]
    session.replace_messages(compacted)
    text = path.read_text(encoding="utf-8")
    assert "compact_snapshot" not in text
    assert path.stat().st_size < size_before
    assert len(text.splitlines()) == 3

    loaded = load_session(session.id)
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["content"].startswith("Previous conversation")

    session.append({"role": "user", "content": "follow-up"})
    loaded = load_session(session.id)
    assert len(loaded.messages) == 3
    assert loaded.messages[-1]["content"] == "follow-up"

    # corrupt tail lines are skipped; cleared todos persist as empty
    from kite.memory.session import load_session_todos, persist_session_todos

    tail_session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    tail_session.append({"role": "user", "content": "keep me"})
    assert tail_session.path is not None
    with tail_session.path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json\n")
    reloaded = load_session(tail_session.id)
    assert reloaded.messages[-1]["content"] == "keep me"
    persist_session_todos(tail_session.id, [{"id": "1", "content": "ship", "status": "pending"}])
    persist_session_todos(tail_session.id, [])
    assert load_session_todos(tail_session.id) == []


def _c_test_resolve_session_path_prefix_is_literal(kite_home) -> None:
    """Empty/glob prefixes must not silently load an arbitrary session."""
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    assert session.path is not None
    assert resolve_session_path(session.id) == session.path
    assert resolve_session_path(session.id[:12]) == session.path
    with pytest.raises(FileNotFoundError):
        resolve_session_path("")
    with pytest.raises(FileNotFoundError):
        resolve_session_path("*")
    with pytest.raises(ValueError):
        resolve_session_path("../../tmp/escape")


def _c_test_session_tail_todos_reverse_and_total(kite_home) -> None:
    from kite.memory.session import load_session_tail, load_session_todos

    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    for i in range(10):
        session.append({"role": "user", "content": f"turn {i}"})
    session.record_event("todo", {"items": [{"id": "1", "content": "old", "status": "pending"}]})
    session.record_event("todo", {"items": [{"id": "2", "content": "new", "status": "in_progress"}]})
    session.record_context_checkpoint("cp-1", label="x")
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json\n")

    tail = load_session_tail(session.id, 3)
    assert [m["content"] for m in tail.messages] == ["turn 7", "turn 8", "turn 9"]
    assert tail.total_messages == 10
    assert tail.meta.id == session.id

    full = load_session_tail(session.id, 50)
    assert len(full.messages) == 10 and full.total_messages == 10

    assert load_session_todos(session.id) == [{"id": "2", "content": "new", "status": "in_progress"}]
    assert load_session_todos("nope-not-persisted-0000") == []


def _c_test_runtime_overlay_roundtrip_without_rewrite(kite_home) -> None:
    from kite.memory.session import list_sessions, load_session

    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hi"})
    size_before = session.path.stat().st_size
    session.note_runtime("groq", "llama-x", "thinking:high")

    reloaded = load_session(session.id)
    assert (reloaded.meta.provider, reloaded.meta.model, reloaded.meta.reasoning) == (
        "groq",
        "llama-x",
        "thinking:high",
    )
    assert [m["content"] for m in reloaded.messages] == ["hi"]
    # Sidecar-only stamp: transcript file untouched.
    assert session.path.stat().st_size == size_before
    metas = {m.id: m for m in list_sessions(limit=10)}
    assert metas[session.id].model == "llama-x"


def _c_test_prune_keeps_newest(kite_home) -> None:
    from kite.memory.session import list_sessions, prune_sessions

    ids = []
    for i in range(5):
        s = create_session(task=f"t{i}", cwd="/tmp", provider="p", model="m")
        s.append({"role": "user", "content": f"msg {i}"})
        ids.append(s.id)
    assert prune_sessions(10) == []
    # dry_run=False: this asserts real deletion, so it must say so explicitly.
    removed = prune_sessions(2, dry_run=False)
    assert [d.id for d in removed] == [ids[2], ids[1], ids[0]]
    assert sorted(m.id for m in list_sessions(limit=10)) == sorted(ids[3:])


def _c_test_open_session_tails_transcript_and_restores_reasoning(tmp_path, kite_home, monkeypatch) -> None:
    from io import StringIO

    from rich.console import Console

    from kite.ui.repl import ChatSession
    from tests.conftest import strip_ansi

    monkeypatch.setattr(ChatSession, "_schedule_release_check_legacy", lambda self: None)
    monkeypatch.setattr(ChatSession, "_prewarm_composer", lambda self: None)
    monkeypatch.setattr(ChatSession, "_startup_banner", lambda self: None)
    monkeypatch.setattr(ChatSession, "_maybe_prompt_project_trust", lambda self: None)
    session = create_session(task="demo", cwd=str(tmp_path), provider="groq", model="llama-x")
    for i in range(70):
        session.append({"role": "user", "content": f"turn {i}"})
    session.note_runtime("groq", "llama-x", "thinking:high")

    chat = ChatSession(cwd=str(tmp_path))
    buf = StringIO()
    chat.console = Console(file=buf, force_terminal=False, width=100)
    chat._open_session(session.id)
    out = strip_ansi(buf.getvalue())
    assert "earlier messages" in out
    assert "turn 69" in out and "turn 0" not in out
    assert chat.state.reasoning == "thinking:high"
    assert (chat.provider, chat.model) == ("groq", "llama-x")
    assert chat._session_id == session.id


def _c_test_checkpoint_redacts_and_confines_session_id(kite_home) -> None:
    import stat

    from kite.config.user import UserConfig
    from kite.memory.context_checkpoint import save_checkpoint

    cfg = UserConfig.load()
    cfg.session_persistence = "redacted"
    cfg.save()
    cp = save_checkpoint(
        session_id="sess-1",
        messages=[{"role": "user", "content": "Bearer SECRETTOKEN"}],
        cwd="/tmp",
    )
    text = (kite_home / "checkpoints" / "sess-1" / f"{cp.id}.json").read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in text
    if __import__("sys").platform != "win32":
        mode = (kite_home / "checkpoints" / "sess-1" / f"{cp.id}.json").stat().st_mode
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR
    with pytest.raises(ValueError):
        save_checkpoint(session_id="../../tmp/escape", messages=[], cwd="/tmp")


def _c_test_write_meta_preserves_durable_rows(kite_home) -> None:
    """F-03: set_exit / replace_messages must not wipe event/checkpoint rows."""
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hi"})
    session.record_event("tool_start", {"tool": "bash"})
    session.record_event("tool_end", {"tool": "bash"})
    session.record_context_checkpoint("cp-1", label="x")
    assert session.path is not None

    session.set_exit("ok")
    text = session.path.read_text(encoding="utf-8")
    assert text.count('"kind": "tool_start"') == 1 or text.count('"kind":"tool_start"') == 1 or '"tool_start"' in text
    assert '"tool_end"' in text
    assert '"context_checkpoint"' in text or '"cp-1"' in text
    assert json.loads(text.splitlines()[0])["exit_status"] == "ok"

    session.replace_messages([{"role": "user", "content": "compacted"}])
    text2 = session.path.read_text(encoding="utf-8")
    assert '"tool_start"' in text2 and '"tool_end"' in text2
    assert '"cp-1"' in text2
    loaded = load_session(session.id)
    assert [m["content"] for m in loaded.messages] == ["compacted"]


def _c_test_atomic_rewrite_failure_leaves_original(kite_home, monkeypatch) -> None:
    """F-04: failed rewrite must leave the original file intact."""
    import os as _os

    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "keep me"})
    assert session.path is not None
    before = session.path.read_bytes()
    leftovers_before = set(session.path.parent.glob("*.tmp"))

    def _boom(*_a, **_k):
        raise OSError("disk full (test)")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(OSError):
        session.set_exit("boom")
    assert session.path.read_bytes() == before
    assert b"keep me" in session.path.read_bytes()
    assert set(session.path.parent.glob("*.tmp")) == leftovers_before


def _c_test_non_object_jsonl_rows_skipped(kite_home) -> None:
    """F-05: valid JSON non-objects must not crash forward loaders."""
    from kite.memory.session import iter_session_messages

    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hello"})
    assert session.path is not None
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write("null\n[]\n\"str\"\n42\n{not-json\n")
    loaded = load_session(session.id)
    assert [m["content"] for m in loaded.messages] == ["hello"]
    assert [m["content"] for m in iter_session_messages(session.id)] == ["hello"]


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_append_meta_lifecycle_and_touch, test_replace_and_load_resilience, test_resolve_session_path_prefix_is_literal."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k0_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_append_meta_lifecycle_and_touch(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_replace_and_load_resilience(kite_home=_k1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_resolve_session_path_prefix_is_literal(kite_home=_k2)
    finally:
        _mp2.undo()

def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_session_tail_todos_reverse_and_total, test_runtime_overlay_roundtrip_without_rewrite, test_prune_keeps_newest."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k1_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_session_tail_todos_reverse_and_total(kite_home=_k0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k1_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_runtime_overlay_roundtrip_without_rewrite(kite_home=_k1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k1_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_prune_keeps_newest(kite_home=_k2)
    finally:
        _mp2.undo()

def test_batch_02(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_open_session_tails_transcript_and_restores_reasoning, test_checkpoint_redacts_and_confines_session_id, test_write_meta_preserves_durable_rows."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _t0 = tmp_path / "t2_0"
        _t0.mkdir(parents=True, exist_ok=True)
        _k0 = tmp_path / "k2_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_open_session_tails_transcript_and_restores_reasoning(tmp_path=_t0, kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k2_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_checkpoint_redacts_and_confines_session_id(kite_home=_k1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k2_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_write_meta_preserves_durable_rows(kite_home=_k2)
    finally:
        _mp2.undo()

def test_batch_03(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_atomic_rewrite_failure_leaves_original, test_non_object_jsonl_rows_skipped."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k3_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_atomic_rewrite_failure_leaves_original(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k3_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_non_object_jsonl_rows_skipped(kite_home=_k1)
    finally:
        _mp1.undo()

