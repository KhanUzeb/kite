"""Agent operating modes: plan (read/plan only) vs build (mutate)."""

from __future__ import annotations

from enum import Enum


class AgentMode(str, Enum):
    PLAN = "plan"
    BUILD = "build"


class ApprovalMode(str, Enum):
    """How much autonomy is granted — surfaced in the prompt itself."""

    AUTO = "auto"  # auto in workspace; ask for paths/bash outside workspace
    TRUST = "trust"  # approve-for-me: auto in workspace, ask on destructive bash
    APPROVE = "approve"  # supervised — reads free; every mutation needs approval
    YOLO = "yolo"  # no approval prompts (still respects plan/readonly)
    READONLY = "readonly"  # never mutate (plan default)


# User-facing aliases (supervised / auto / yolo) map to canonical modes.
APPROVAL_ALIASES: dict[str, str] = {
    "supervised": "approve",
    "auto": "auto",
    "yolo": "yolo",
    "trust": "trust",
    "approve": "approve",
    "readonly": "readonly",
}


def parse_approval_mode(raw: str | None, *, default: ApprovalMode | None = None) -> ApprovalMode:
    """Resolve CLI/REPL approval strings, including supervised/yolo aliases."""
    if not raw:
        return default or ApprovalMode.AUTO
    key = raw.strip().lower()
    canonical = APPROVAL_ALIASES.get(key, key)
    try:
        return ApprovalMode(canonical)
    except ValueError:
        return default or ApprovalMode.AUTO


def approval_display_name(mode: ApprovalMode) -> str:
    """Short label for footer / approval UI."""
    if mode is ApprovalMode.APPROVE:
        return "supervised"
    if mode is ApprovalMode.YOLO:
        return "yolo"
    return mode.value


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
# Plan mode may run read-only bash (rg, head, cat, …) for token-efficient inspection.
PLAN_TOOLS = frozenset({*READONLY_TOOLS, "todo_write", "todo_read", "task", "bash"})

BUILD_TOOLS = frozenset({*READONLY_TOOLS, *MUTATING_TOOLS, "todo_write", "todo_read", "task"})


def default_approval(mode: AgentMode) -> ApprovalMode:
    return ApprovalMode.READONLY if mode is AgentMode.PLAN else ApprovalMode.APPROVE


def filter_enabled(enabled: list[str], allowed: frozenset[str]) -> list[str]:
    return [name for name in enabled if name in allowed]


def tools_for_mode(mode: AgentMode, enabled: list[str]) -> list[str]:
    allow = PLAN_TOOLS if mode is AgentMode.PLAN else BUILD_TOOLS
    return filter_enabled(enabled, allow)
