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
from kite.memory.session_analytics import SessionStats, save_session_stats, scan_session_file


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


def test_session_stats_and_events(kite_home, tmp_path) -> None:
    session = create_session(task="demo", cwd=str(tmp_path), provider="groq", model="test")
    stats = SessionStats(
        session_id=session.id,
        created_at=1.0,
        updated_at=10.0,
        duration_s=9.0,
        provider="groq",
        model="test",
        cwd=str(tmp_path),
        tool_calls=3,
        tool_counts={"read": 2, "bash": 1},
        api_calls=5,
        cost=0.12,
        estimated_tokens=4000,
        cache_hit_tokens=800,
    )
    save_session_stats(stats)
    row = scan_session_file(session.save())
    assert row is not None
    assert row.tool_calls == 3
    assert row.cache_hit_tokens >= 800

    events_session = create_session(task="events", cwd=str(tmp_path), provider="groq", model="test")
    events_session.record_event("tool_end", {"tool": "grep", "ok": True})
    events_session.record_event("compact", {"before": 10, "after": 4})
    events_session.record_event("tool_end", {"tool": "edit", "ok": False, "blocked": True})
    event_row = scan_session_file(events_session._session_path())
    assert event_row is not None
    assert event_row.compaction_count == 1
    assert event_row.tool_blocked == 1


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
