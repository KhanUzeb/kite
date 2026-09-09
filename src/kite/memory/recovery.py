"""Auto-recovery and resume-after-failure decisions."""

from __future__ import annotations

from kite.memory.continuity import should_budget_auto_continue

RECOVERABLE_EXITS = frozenset(
    {"ProviderFault", "LimitsExceeded", "TimeExceeded", "Stalled", "Error"}
)
_DEFAULT_MAX_RECOVERY = 3
_PROVIDER_FAULT_AUTO_RETRIES = 2


def should_auto_recover(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int = _DEFAULT_MAX_RECOVERY,
    goal_active: bool = False,
    todos: list[dict] | None = None,
    tool_call_count: int = 0,
    inbox_queued: bool = False,
) -> bool:
    """Whether the REPL should chain another resume turn after a recoverable stop."""
    if inbox_queued:
        return False
    if continues_used >= max_continues:
        return False
    status = (exit_status or "").strip()
    if status in {"Submitted", "Interrupted", "Cancelled"}:
        return False
    if goal_active and status in RECOVERABLE_EXITS:
        return True
    if status == "ProviderFault":
        return continues_used < _PROVIDER_FAULT_AUTO_RETRIES
    if status == "LimitsExceeded":
        return should_budget_auto_continue(
            exit_status=status,
            continues_used=continues_used,
            max_continues=max_continues,
            todos=todos,
            tool_call_count=tool_call_count,
            inbox_queued=inbox_queued,
        )
    if status == "TimeExceeded" and (goal_active or (todos and tool_call_count > 0)):
        return True
    return False


def decide_recovery_continue(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int = _DEFAULT_MAX_RECOVERY,
    goal_active: bool = False,
    goal_objective: str = "",
    todos: list[dict] | None = None,
    tool_call_count: int = 0,
    inbox_queued: bool = False,
) -> str:
    """Return 'continue' or 'stop' for the REPL recovery chain."""
    if should_auto_recover(
        exit_status=exit_status,
        continues_used=continues_used,
        max_continues=max_continues,
        goal_active=goal_active,
        todos=todos,
        tool_call_count=tool_call_count,
        inbox_queued=inbox_queued,
    ):
        return "continue"
    return "stop"


def build_recovery_follow_up(
    *,
    exit_status: str,
    continuity_markdown: str,
    goal_objective: str = "",
) -> str:
    status = (exit_status or "").strip()
    if goal_objective.strip():
        header = (
            "Continue working toward the active goal:\n\n"
            f"{goal_objective.strip()}\n\n"
        )
    else:
        header = "Continue the unfinished work from where we left off.\n\n"
    if status == "ProviderFault":
        header += (
            "The previous attempt stopped due to a provider or network error. "
            "Session transcript is saved — pick up from the continuity brief.\n\n"
        )
    elif status in {"LimitsExceeded", "TimeExceeded"}:
        header += (
            "The previous attempt hit step/cost/time limits. "
            "Resume efficiently from the continuity brief.\n\n"
        )
    body = (continuity_markdown or "").strip()
    tail = (
        "Do not restart from scratch. Pick up at Next / Open todos and finish "
        "remaining work."
    )
    if body:
        return f"{header}{body}\n\n{tail}"
    return f"{header}{tail}"
