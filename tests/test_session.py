"""Session persistence — append-only messages and meta timestamps."""

from __future__ import annotations

import json
import time

from kite.memory.session import Session, SessionMeta, create_session


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
    assert lines[0].startswith('{"type": "meta"')
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
