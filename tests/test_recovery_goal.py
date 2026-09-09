"""Goal mode and resume-after-failure recovery."""

from __future__ import annotations

from kite.memory.goal import SessionGoal, format_goal_section, load_session_goal, save_session_goal
from kite.memory.recovery import (
    build_recovery_follow_up,
    decide_recovery_continue,
    should_auto_recover,
)
from kite.memory.session import load_session_todos, persist_session_todos


def test_session_goal_roundtrip(kite_home) -> None:
    save_session_goal("sess-1", SessionGoal(objective="Ship feature X", status="active"))
    loaded = load_session_goal("sess-1")
    assert loaded is not None
    assert loaded.active
    assert "Ship feature X" in loaded.objective
    save_session_goal("sess-1", None)
    assert load_session_goal("sess-1") is None


def test_format_goal_section() -> None:
    text = format_goal_section("Keep tests green")
    assert "Active goal" in text
    assert "Keep tests green" in text


def test_should_auto_recover_provider_fault() -> None:
    assert should_auto_recover(exit_status="ProviderFault", continues_used=0, goal_active=False)
    assert not should_auto_recover(exit_status="ProviderFault", continues_used=2, goal_active=False)
    assert should_auto_recover(exit_status="Interrupted", continues_used=0, goal_active=False) is False


def test_goal_mode_auto_recover() -> None:
    assert should_auto_recover(
        exit_status="ProviderFault",
        continues_used=0,
        goal_active=True,
    )
    assert decide_recovery_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=3,
        goal_active=True,
        todos=[{"status": "pending", "content": "fix tests"}],
        tool_call_count=1,
    ) == "continue"


def test_build_recovery_follow_up_includes_goal() -> None:
    text = build_recovery_follow_up(
        exit_status="ProviderFault",
        continuity_markdown="## Continuity\n- Mission: x",
        goal_objective="Finish migration",
    )
    assert "Finish migration" in text
    assert "provider" in text.lower()


def test_persist_and_load_session_todos(kite_home, workspace) -> None:
    from kite.memory.session import create_session

    session = create_session(
        task="demo",
        cwd=str(workspace),
        provider="groq",
        model="test",
    )
    items = [{"id": "1", "content": "run pytest", "status": "pending"}]
    persist_session_todos(session.id, items)
    loaded = load_session_todos(session.id)
    assert loaded and loaded[0]["content"] == "run pytest"


def test_kite_resume_retry_parser() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["resume", "--last", "--retry", "abc12345"])
    assert args.last is True
    assert args.retry is True
    assert args.session == "abc12345"
