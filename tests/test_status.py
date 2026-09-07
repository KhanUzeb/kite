"""Status line and context meter."""

from __future__ import annotations

from kite.ui.render import render_status
from kite.ui.state import SessionUiState
from kite.ui.status import context_meter, format_status_tail


def test_set_context_usage_updates_meter() -> None:
    state = SessionUiState(window=100_000)
    state.set_context_usage(total_tokens=25_000, window=100_000)
    assert state.tokens == 25_000
    assert state.context_pct == 0.25
    meter = context_meter(state.context_pct)
    assert "25%" in meter


def test_context_meter_renders_bar() -> None:
    text = context_meter(0.5)
    assert "ctx" in text
    assert "50%" in text
    assert "█" in text
    assert "░" in text


def test_context_meter_empty_when_unknown() -> None:
    assert context_meter(None) == ""


def test_verification_badge_hidden_when_idle() -> None:
    from kite.ui.status import format_status_tail

    tail = format_status_tail(SessionUiState(verification_status="idle", provider="p", model="m"))
    assert "verify" not in tail
    assert "unverified" not in tail


def test_format_status_tail_includes_cache_and_agents() -> None:
    from kite.ui.status import format_metrics_tail

    state = SessionUiState(
        provider="groq",
        model="llama",
        tokens=4000,
        window=8000,
        cost=0.12,
        cache_hit_tokens=500,
        cache_hit_ratio=0.25,
        active_subagents=2,
    )
    tail = format_status_tail(state)
    metrics = format_metrics_tail(state)
    assert "cache" in metrics
    assert "25%" in metrics
    assert "4.00k tok" in metrics
    assert "agents 2" in tail
    assert "$0.120" in metrics


def test_format_running_status_includes_activity_preview() -> None:
    from kite.ui.status import format_running_status

    state = SessionUiState(
        busy=True,
        running_label="pytest -q",
        running_since="12:00:00",
        activity_preview="tests passed",
    )
    text = format_running_status(state)
    assert "pytest -q" in text
    assert "tests passed" in text


def test_cache_meter_renders_bar() -> None:
    from kite.ui.status import cache_meter

    text = cache_meter(0.25)
    assert "cache" in text
    assert "25%" in text


def test_format_status_tail_plan_shows_checklist_progress() -> None:
    from kite.agent.mode import AgentMode, ApprovalMode
    from kite.ui.state import TodoItem

    state = SessionUiState(
        mode=AgentMode.PLAN,
        approval=ApprovalMode.READONLY,
        model="m",
        todos=[
            TodoItem(id="1", content="explore", status="completed"),
            TodoItem(id="2", content="ship", status="pending"),
        ],
    )
    tail = format_status_tail(state)
    assert "plan" in tail
    assert "readonly" in tail
    assert "list 1/2" in tail


def test_render_status_matches_format_status_tail() -> None:
    state = SessionUiState(
        provider="groq",
        model="llama",
        tokens=4000,
        window=8000,
        cost=0.12,
        cache_hit_tokens=500,
        cache_hit_ratio=0.25,
        active_subagents=2,
    )
    rendered = render_status(state).plain
    assert format_status_tail(state) in rendered
    assert rendered.startswith("kite")
