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
    load_session,
    resolve_session_path,
)


def test_append_meta_lifecycle_and_touch(kite_home, monkeypatch) -> None:
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

    # updated_at refreshes through the sidecar without rewriting the header.
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
    before = load_session(tracked.id).meta.updated_at
    header = tracked.path.read_bytes().split(b"\n", 1)[0]
    with monkeypatch.context() as patch:
        patch.setattr(time, "time", lambda: before + 1.0)
        tracked.append({"role": "user", "content": "x"})
    after = load_session(tracked.id).meta.updated_at
    assert tracked.path.read_bytes().split(b"\n", 1)[0] == header
    assert after > before

    # Appending must not reopen the transcript for reading or rewrite its header.
    touch = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    touch.append({"role": "user", "content": "hi"})
    touch_path = touch.path
    assert touch_path is not None
    original_open = Path.open

    def spy_open(self: Path, mode="r", *args, **kwargs):
        if self == touch_path:
            assert mode == "a", "append reopened the transcript instead of using the sidecar"
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    touch.append({"role": "assistant", "content": "hello"})


def test_replace_and_load_resilience(kite_home) -> None:
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


def test_resolve_session_path_prefix_is_literal(kite_home) -> None:
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


def test_session_tail_todos_reverse_and_total(kite_home) -> None:
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

    # Legacy snapshots replace older history without reversing their own order.
    snapshot = [{"role": "user", "content": f"snapshot {i}"} for i in range(4)]
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "compact_snapshot", "messages": snapshot}) + "\n")
        handle.write(json.dumps({"type": "message", "message": {"role": "user", "content": "after"}}) + "\n")
    assert [m["content"] for m in load_session_tail(session.id, 3).messages] == [
        "snapshot 2", "snapshot 3", "after",
    ]
    assert load_session_tail(session.id, 50).messages == load_session(session.id).messages
    assert load_session_tail(session.id, 0).messages == []

    # A row spanning multiple reverse-read chunks must be assembled just once.
    long_message = {"role": "user", "content": "αβγ" * 30_000}
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "message", "message": long_message}, ensure_ascii=False))
    assert load_session_tail(session.id, 1).messages == [long_message]
    assert load_session_tail(session.id, 2).messages == [
        {"role": "user", "content": "after"}, long_message,
    ]


def test_runtime_overlay_roundtrip_without_rewrite(kite_home) -> None:
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


def test_open_session_tails_transcript_and_restores_reasoning(workspace, kite_home, monkeypatch) -> None:
    from io import StringIO

    from rich.console import Console

    from kite.ui.repl import ChatSession
    from tests.conftest import strip_ansi

    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)
    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    session = create_session(task="demo", cwd=str(workspace), provider="groq", model="llama-x")
    for i in range(70):
        session.append({"role": "user", "content": f"turn {i}"})
    session.note_runtime("groq", "llama-x", "thinking:high")

    chat = ChatSession(cwd=str(workspace))
    buf = StringIO()
    chat.console = Console(file=buf, force_terminal=False, width=100)
    chat._open_session(session.id)
    out = strip_ansi(buf.getvalue())
    assert "earlier messages" in out
    assert "turn 69" in out and "turn 0" not in out
    assert chat.state.reasoning == "thinking:high"
    assert (chat.provider, chat.model) == ("groq", "llama-x")
    assert chat._session_id == session.id


def test_checkpoint_redacts_and_confines_session_id(kite_home) -> None:
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


def test_write_meta_preserves_durable_rows(kite_home) -> None:
    """F-03: set_exit / replace_messages must not wipe event/checkpoint rows."""
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hi"})
    session.record_event("tool_start", {"tool": "bash"})
    session.record_event("tool_end", {"tool": "bash"})
    session.record_context_checkpoint("cp-1", label="x")
    assert session.path is not None
    durable = [
        row for line in session.path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))["type"] in {"event", "context_checkpoint"}
    ]

    session.set_exit("ok")
    rows = [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]
    assert [row for row in rows if row["type"] in {"event", "context_checkpoint"}] == durable
    assert rows[0]["exit_status"] == "ok"

    session.replace_messages([{"role": "user", "content": "compacted"}])
    rows = [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]
    assert [row for row in rows if row["type"] in {"event", "context_checkpoint"}] == durable
    loaded = load_session(session.id)
    assert [m["content"] for m in loaded.messages] == ["compacted"]


def test_atomic_rewrite_failure_leaves_original(kite_home, monkeypatch) -> None:
    """F-04: failed rewrite must leave the original file intact."""
    import os as _os

    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "keep me"})
    assert session.path is not None
    before = session.path.read_bytes()
    leftovers_before = set(session.path.parent.glob("*.tmp"))
    sidecar = session.path.with_suffix(".meta")
    sidecar_before = sidecar.read_bytes()
    real_replace = _os.replace

    def _boom(src, dst):
        if _os.name != "nt":
            assert Path(src).stat().st_mode & 0o777 == 0o600
        raise OSError("disk full (test)")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(OSError):
        session.set_exit("boom")
    assert session.path.read_bytes() == before
    assert b"keep me" in session.path.read_bytes()
    assert set(session.path.parent.glob("*.tmp")) == leftovers_before

    with pytest.raises(OSError):
        session.append({"role": "user", "content": "still durable"})
    assert sidecar.read_bytes() == sidecar_before
    assert load_session(session.id).messages[-1]["content"] == "still durable"
    assert set(session.path.parent.glob("*.tmp")) == leftovers_before

    monkeypatch.setattr(_os, "replace", real_replace)

    def fail_sync(fd):
        raise OSError("fsync failed (test)")

    monkeypatch.setattr(_os, "fsync", fail_sync)
    before = session.path.read_bytes()
    with pytest.raises(OSError, match="fsync failed"):
        session.save()
    assert session.path.read_bytes() == before
    assert set(session.path.parent.glob("*.tmp")) == leftovers_before


def test_non_object_jsonl_rows_skipped(kite_home) -> None:
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
