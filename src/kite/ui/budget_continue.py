"""REPL budget-continue chain helpers (pure decisions for tests)."""

from __future__ import annotations

from kite.memory.continuity import next_budget_action


def decide_budget_continue(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int = 2,
    todos: list[dict] | None = None,
    tool_call_count: int = 0,
    inbox_queued: bool = False,
) -> str:
    """Return 'continue' or 'stop' for the REPL turn chain."""
    return next_budget_action(
        exit_status=exit_status,
        continues_used=continues_used,
        max_continues=max_continues,
        todos=todos,
        tool_call_count=tool_call_count,
        inbox_queued=inbox_queued,
    )
