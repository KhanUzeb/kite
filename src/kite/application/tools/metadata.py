"""Tool side-effect metadata registry."""

from __future__ import annotations

from kite.application.tools.contracts import SideEffect

TOOL_SIDE_EFFECTS: dict[str, tuple[SideEffect, ...]] = {
    "read": ("read",),
    "write": ("workspace_write",),
    "edit": ("workspace_write",),
    "bash": ("process_control", "workspace_write"),
    "grep": ("read",),
    "glob": ("read",),
    "ls": ("read",),
    "web_search": ("network", "cost_bearing"),
    "web_fetch": ("network",),
    "task": ("process_control", "cost_bearing"),
    "memory_write": ("workspace_write", "sensitive_read"),
    "apply_patch": ("workspace_write",),
}


def side_effects_for(tool_name: str) -> tuple[SideEffect, ...]:
    return TOOL_SIDE_EFFECTS.get(tool_name, ("read", "workspace_write"))
