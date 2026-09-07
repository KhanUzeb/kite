"""Session persistence and analytics."""

from __future__ import annotations

import json
import time
from pathlib import Path

from kite.memory.session import Session, SessionMeta, create_session, format_meta_line, load_session
from kite.memory.session_analytics import SessionStats, save_session_stats, scan_session_file


def test_append_messages_without_full_rewrite(kite_home) -> None:
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


def test_meta_updated_at_refreshed_on_append(kite_home) -> None:
    meta = SessionMeta(
        id="test-id",
        created_at=time.time(),
        updated_at=1.0,
        cwd="/tmp",
        provider="p",
        model="m",
        task="t",
    )
    session = Session(meta=meta)
    session.save()
    before = json.loads(session.path.read_text(encoding="utf-8").splitlines()[0])["updated_at"]

    time.sleep(0.01)
    session.append({"role": "user", "content": "x"})
    after = json.loads(session.path.read_text(encoding="utf-8").splitlines()[0])["updated_at"]
    assert after > before


def test_meta_line_length_stable_on_timestamp_patch() -> None:
    meta = SessionMeta(
        id="x",
        created_at=1_700_000_000.0,
        updated_at=1_700_000_000.0,
        cwd="/tmp",
        provider="p",
        model="m",
        task="t",
    )
    first = format_meta_line(meta)
    meta.updated_at = 1_700_000_123.456789
    second = format_meta_line(meta)
    assert len(first) == len(second)


def test_touch_meta_reads_only_first_line(kite_home, monkeypatch) -> None:
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hi"})
    path = session.path
    assert path is not None

    original_read = Path.read_bytes

    def spy_read_bytes(self: Path) -> bytes:
        if self == path:
            raise AssertionError("touch_meta should not read the whole session file")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    session.append({"role": "assistant", "content": "hello"})


def test_replace_messages_rewrites_session_file(kite_home) -> None:
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


def test_save_and_scan_session_stats(kite_home, tmp_path) -> None:
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


def test_scan_session_events(kite_home, tmp_path) -> None:
    session = create_session(task="events", cwd=str(tmp_path), provider="groq", model="test")
    session.record_event("tool_end", {"tool": "grep", "ok": True})
    session.record_event("compact", {"before": 10, "after": 4})
    session.record_event("tool_end", {"tool": "edit", "ok": False, "blocked": True})
    row = scan_session_file(session._session_path())
    assert row is not None
    assert row.compaction_count == 1
    assert row.tool_blocked == 1
