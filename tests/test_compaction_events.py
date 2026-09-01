"""Compaction ratio and durable session events."""

from __future__ import annotations

import json

from kite.context.window import ContextUsage, should_compact
from kite.memory.session import create_session, load_session


def test_should_compact_at_eighty_percent() -> None:
    usage = ContextUsage(
        total_tokens=102_400,
        system_tokens=1000,
        message_tokens=101_400,
        tool_tokens=0,
        message_count=10,
        window=128_000,
    )
    assert should_compact(usage, ratio=0.80)
    assert not should_compact(usage, ratio=0.85)


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
