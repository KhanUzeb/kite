"""Durable rollout events in session JSONL."""

from __future__ import annotations

import json

from kite.memory.session import create_session, load_session


def test_session_records_durable_events(kite_home) -> None:
    session = create_session(task="t", cwd="/tmp", provider="openai", model="gpt-4")
    session.record_event("turn_start", {"n": 1})
    session.record_event("stream_delta", {"text": "ignored"})  # not durable
    path = session.path or session._session_path()
    kinds = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("type") == "event":
                kinds.append(row["kind"])
    assert kinds == ["turn_start"]

    loaded = load_session(session.id)
    assert loaded.meta.id == session.id
