"""Status line and context meter."""

from __future__ import annotations

from kite.ui.state import SessionUiState
from kite.ui.status import context_meter, format_status_tail
from kite.ui.render import render_status


def test_context_meter_renders_bar() -> None:
    text = context_meter(0.5)
    assert "ctx" in text
    assert "50%" in text
    assert "█" in text
    assert "░" in text


def test_context_meter_empty_when_unknown() -> None:
    assert context_meter(None) == ""


def test_format_status_tail_includes_cache_and_agents() -> None:
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
    assert "cache 25%" in tail
    assert "agents 2" in tail
    assert "$0.120" in tail


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
