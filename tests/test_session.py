"""Session persistence — append-only messages and meta timestamps."""

from __future__ import annotations

import json
import time
from pathlib import Path

from kite.memory.session import Session, SessionMeta, create_session, format_meta_line


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
