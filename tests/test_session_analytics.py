"""Session analytics and dashboard tests."""

from __future__ import annotations

import json

from kite.memory.session import create_session
from kite.memory.session_analytics import (
    SessionStats,
    build_dashboard_summary,
    build_user_profile,
    list_session_events,
    save_session_stats,
    scan_session_file,
)


def test_user_profile_has_username(kite_home) -> None:
    profile = build_user_profile()
    assert profile.username
    assert profile.kite_home
    assert profile.sessions_dir


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
    path = session.save()
    row = scan_session_file(path)
    assert row is not None
    assert row.tool_calls == 3
    assert row.cost == 0.12
    assert row.cache_hit_tokens >= 800
    assert row.cwd == str(tmp_path)


def test_build_dashboard_summary(kite_home, tmp_path) -> None:
    for i in range(2):
        s = create_session(task=f"t{i}", cwd=str(tmp_path), provider="groq", model="m")
        save_session_stats(
            SessionStats(
                session_id=s.id,
                created_at=float(i),
                updated_at=float(10 + i),
                duration_s=float(5 + i),
                exit_status="Submitted" if i == 0 else "Error",
                tool_calls=i + 1,
                tool_counts={"read": i + 1},
            )
        )
        s.save()
    summary = build_dashboard_summary(limit=10)
    assert summary.session_count >= 2
    assert summary.total_tool_calls >= 3
    assert summary.user.username
    assert summary.completed_sessions >= 1
    assert summary.failed_sessions_count >= 1


def test_scan_session_events(kite_home, tmp_path) -> None:
    session = create_session(task="events", cwd=str(tmp_path), provider="groq", model="test")
    session.record_event("tool_end", {"tool": "grep", "ok": True})
    session.record_event("turn_start", {})
    session.record_event("compact", {"before": 10, "after": 4})
    session.record_event("agent_start", {"mode": "build", "approval": "auto"})
    session.record_event("tool_end", {"tool": "edit", "ok": False, "blocked": True})
    path = session._session_path()
    row = scan_session_file(path)
    assert row is not None
    assert row.tool_calls == 2
    assert row.turn_count == 1
    assert row.compaction_count == 1
    assert row.tool_counts.get("grep") == 1
    assert row.tool_failures == 1
    assert row.tool_blocked == 1
    assert row.write_edits == 1
    assert row.mode == "build"
    assert row.approval == "auto"
    events = list_session_events(path, limit=10)
    assert len(events) >= 4


def test_dashboard_json_includes_user(kite_home, capsys) -> None:
    import argparse

    from kite.cli.dashboard import cmd_dashboard

    args = argparse.Namespace(session=None, limit=10, watch=0, json=True)
    code = cmd_dashboard(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out or captured.err)
    assert "user" in data
    assert data["user"]["username"]
