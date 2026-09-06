"""Budget continue decision used by the REPL turn chain."""

from __future__ import annotations

from kite.ui.budget_continue import decide_budget_continue


def test_decide_budget_continue_yes() -> None:
    assert (
        decide_budget_continue(
            exit_status="LimitsExceeded",
            continues_used=0,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=2,
            inbox_queued=False,
        )
        == "continue"
    )


def test_decide_budget_continue_stop_at_cap() -> None:
    assert (
        decide_budget_continue(
            exit_status="LimitsExceeded",
            continues_used=2,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=2,
            inbox_queued=False,
        )
        == "stop"
    )
