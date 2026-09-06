"""Continuity briefs + budget auto-continue gates."""

from __future__ import annotations

from kite.memory.continuity import (
    ContinuityBrief,
    build_continuity_brief,
    has_unfinished_work,
    latest_continuity_markdown,
    maybe_pin_project_fact,
    next_budget_action,
    save_continuity,
    should_budget_auto_continue,
)
from kite.memory.store import MemoryStore


def test_build_continuity_brief_includes_mission_and_todos() -> None:
    messages = [
        {"role": "user", "content": "Add auth tests"},
        {"role": "assistant", "content": "Edited tests/test_auth.py"},
    ]
    todos = [{"status": "in_progress", "content": "write failing test"}]
    brief = build_continuity_brief(messages=messages, todos=todos, task="Add auth tests")
    md = brief.to_markdown()
    assert "## Continuity" in md
    assert "Add auth tests" in md
    assert "write failing test" in md


def test_has_unfinished_work_open_todos() -> None:
    assert has_unfinished_work(
        todos=[{"status": "pending", "content": "x"}],
        exit_status="LimitsExceeded",
        tool_call_count=3,
    )


def test_has_unfinished_work_false_when_submitted() -> None:
    assert not has_unfinished_work(
        todos=[{"status": "completed", "content": "x"}],
        exit_status="Submitted",
        tool_call_count=5,
    )


def test_should_budget_auto_continue_caps_and_inbox() -> None:
    assert should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
    assert not should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=2,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
    assert not should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=True,
    )
    assert not should_budget_auto_continue(
        exit_status="Interrupted",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )


def test_next_budget_action() -> None:
    assert (
        next_budget_action(
            exit_status="LimitsExceeded",
            continues_used=0,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=1,
            inbox_queued=False,
        )
        == "continue"
    )
    assert (
        next_budget_action(
            exit_status="Submitted",
            continues_used=0,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=1,
            inbox_queued=False,
        )
        == "stop"
    )


def test_maybe_pin_project_fact_dedupes(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    brief = ContinuityBrief(mission="x", paths=["src/auth.py"], constraints=["no new deps"])
    assert maybe_pin_project_fact(store, brief) is True
    assert maybe_pin_project_fact(store, brief) is False


def test_save_and_load_continuity(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    brief = build_continuity_brief(
        messages=[{"role": "user", "content": "Fix login"}],
        todos=[{"status": "pending", "content": "patch handler"}],
        task="Fix login",
    )
    save_continuity(store=store, brief=brief, session_id="s1", cwd=str(workspace))
    md = latest_continuity_markdown(store, session_id="s1")
    assert "## Continuity" in md
    assert "Fix login" in md
