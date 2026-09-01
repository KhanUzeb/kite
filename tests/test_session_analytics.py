"""Session analytics and dashboard tests."""

from __future__ import annotations

import json

from kite.memory.session_analytics import (
    build_dashboard_summary,
    save_session_stats,
    scan_session_file,
    SessionStats,
)
from kite.memory.session import create_session


def test_save_and_scan_session_stats(kite_home, tmp_path) -> None:
    session = create_session(task="demo", cwd=str(tmp_path), provider="groq", model="test")
    stats = SessionStats(
        session_id=session.id,
        created_at=1.0,
        updated_at=10.0,
        duration_s=9.0,
        provider="groq",
        model="test",
        tool_calls=3,
        tool_counts={"read": 2, "bash": 1},
        api_calls=5,
        cost=0.12,
        estimated_tokens=4000,
        cache_hit_tokens=800,
    )
    save_session_stats(stats)
    path = session.save()
    row = scan_session_file(path)
    assert row is not None
    assert row.tool_calls == 3
    assert row.cost == 0.12
    assert row.cache_hit_tokens >= 800


def test_build_dashboard_summary(kite_home, tmp_path) -> None:
    for i in range(2):
        s = create_session(task=f"t{i}", cwd=str(tmp_path), provider="groq", model="m")
        save_session_stats(
            SessionStats(
                session_id=s.id,
                created_at=float(i),
                updated_at=float(10 + i),
                duration_s=float(5 + i),
                tool_calls=i + 1,
                tool_counts={"read": i + 1},
            )
        )
        s.save()
    summary = build_dashboard_summary(limit=10)
    assert summary.session_count >= 2
    assert summary.total_tool_calls >= 3


def test_scan_session_events(kite_home, tmp_path) -> None:
    session = create_session(task="events", cwd=str(tmp_path), provider="groq", model="test")
    session.record_event("tool_end", {"tool": "grep", "ok": True})
    session.record_event("turn_start", {})
    session.record_event("compact", {"before": 10, "after": 4})
    path = session._session_path()
    row = scan_session_file(path)
    assert row is not None
    assert row.tool_calls == 1
    assert row.turn_count == 1
    assert row.compaction_count == 1
    assert row.tool_counts.get("grep") == 1
