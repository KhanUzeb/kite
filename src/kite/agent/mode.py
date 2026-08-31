"""Agent operating modes: plan (read/plan only) vs build (mutate)."""

from __future__ import annotations

from enum import Enum


class AgentMode(str, Enum):
    PLAN = "plan"
    BUILD = "build"


class ApprovalMode(str, Enum):
    """How much autonomy is granted — surfaced in the prompt itself."""

    AUTO = "auto"  # mutate inside sandbox without asking
    TRUST = "trust"  # approve-for-me: auto in workspace, ask on destructive bash
    APPROVE = "approve"  # ask on every gated tool
    READONLY = "readonly"  # never mutate (plan default)


# Cheap, read-only tools — unrestricted in both modes.
READONLY_TOOLS = frozenset(
    {
        "read", "grep", "glob", "ls", "set_cwd", "skill", "todo_read", "webfetch", "websearch", "webcrawl",
        "subagent", "task",
        "memory", "gh_issue", "gh_pr", "gh_prs", "gh_runs", "gh_run",
    }
)

# Read-only tools safe to run concurrently in one model turn (deterministic order preserved).
PARALLEL_SAFE_TOOLS = frozenset({"read", "grep", "glob", "ls"})

# Mutating / side-effecting — gated, and blocked entirely in plan mode.
MUTATING_TOOLS = frozenset({"write", "edit", "bash"})

# Plan mode may write the live checklist so the user can see the proposed work.
PLAN_TOOLS = frozenset({*READONLY_TOOLS, "todo_write", "todo_read", "task"})

BUILD_TOOLS = frozenset({*READONLY_TOOLS, *MUTATING_TOOLS, "todo_write", "todo_read", "task"})


def default_approval(mode: AgentMode) -> ApprovalMode:
    return ApprovalMode.READONLY if mode is AgentMode.PLAN else ApprovalMode.APPROVE


def tools_for_mode(mode: AgentMode, enabled: list[str]) -> list[str]:
    allow = PLAN_TOOLS if mode is AgentMode.PLAN else BUILD_TOOLS
    return [name for name in enabled if name in allow]
