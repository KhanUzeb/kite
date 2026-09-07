"""RunDisplay event handling (no TTY)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME


def _display() -> tuple[StringIO, RunDisplay]:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    return buf, RunDisplay(console, state=SessionUiState(), quiet=False)


def test_cost_estimate_stores_budget_skips_print_when_busy() -> None:
    buf, display = _display()
    display.state.busy = True
    display(
        Event(
            "cost_estimate",
            payload={"cost_limit": 5.0, "note": "Budget: ≤$5.00 across up to 40 model calls"},
        )
    )
    assert display.state.budget_limit == 5.0
    assert "Budget" not in buf.getvalue()


def test_failed_tool_end_shows_collapsed_error() -> None:
    buf, display = _display()
    err = "Command failed\nline two\nline three\nline four"
    display(Event("tool_end", payload={"tool": "bash", "ok": False, "error": err}))
    out = buf.getvalue()
    assert "line two" in out
    assert "line three" in out


def test_agent_end_clears_budget_limit() -> None:
    buf, display = _display()
    display.state.budget_limit = 5.0
    display(Event("agent_end", payload={"exit_status": "Submitted", "submission": "done"}))
    assert display.state.budget_limit is None


def test_compact_event_updates_context_meter() -> None:
    buf, display = _display()
    display(
        Event(
            "compact",
            payload={"before": 42, "after": 12, "total_tokens": 24_000, "window": 128_000},
        )
    )
    assert display.state.tokens == 24_000
    assert display.state.window == 128_000
    assert "42 → 12" in buf.getvalue()


def test_failed_verification_still_warns() -> None:
    buf, display = _display()
    display(
        Event(
            "artifact",
            payload={"status": "failed", "artifact_count": 1, "diff_count": 0, "gaps": ["pytest failed"], "artifacts": []},
        )
    )
    display(
        Event(
            "agent_end",
            payload={
                "exit_status": "Submitted",
                "submission": "done",
                "verification_status": "failed",
                "verification": {"status": "failed", "artifact_count": 1, "gaps": ["pytest failed"]},
            },
        )
    )
    out = buf.getvalue()
    assert "couldn't fully verify" in out


def test_limits_exceeded_is_soft_pause_with_continue_hint() -> None:
    buf, display = _display()
    display(
        Event(
            "agent_end",
            payload={
                "exit_status": "LimitsExceeded",
                "content": "step budget 40/40",
                "submission": "steps",
                "limit_kind": "steps",
                "steps": 40,
                "step_limit": 40,
            },
        )
    )
    out = buf.getvalue().lower()
    assert "continue" in out
