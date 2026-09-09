"""TUI polish — status segments, empty states, panel styling."""

from __future__ import annotations

from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.empty import render_empty
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import format_status_tail, render_status, status_segments


def test_status_segments_match_tail() -> None:
    state = SessionUiState(
        mode=AgentMode.PLAN,
        approval=ApprovalMode.READONLY,
        model="llama",
        provider="groq",
        todos=[TodoItem(id="1", content="ship", status="in_progress")],
    )
    tail = format_status_tail(state)
    rendered = render_status(state).plain
    for text, _style in status_segments(state):
        assert text in tail
        assert text in rendered


def test_render_empty_includes_hint() -> None:
    line = render_empty("no jobs", hint="/kill all").plain
    assert "no jobs" in line
    assert "/kill all" in line
