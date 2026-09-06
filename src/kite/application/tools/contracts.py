"""Tool execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["ok", "error", "denied", "cancelled"]

SideEffect = Literal[
    "workspace_read",
    "workspace_write",
    "destructive",
    "network",
    "durable_memory",
    "package_or_skill_install",
    "nested_agent",
    "long_running",
    # Legacy aliases — prefer canonical names above
    "read",
    "external_write",
    "sensitive_read",
    "process_control",
    "cost_bearing",
]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    source: str = "model"


@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool: str
    normalized_arguments: dict[str, Any]
    canonical_targets: tuple[str, ...]
    side_effects: tuple[SideEffect, ...]
    workspace: str
    command_digest: str = ""
    content_digest: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    mandatory: bool = False
    policy_version: str = "0.9.0"
    scope: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    status: ToolStatus
    ok: bool
    output: str = ""
    error: str = ""
    changed_paths: tuple[str, ...] = ()
    duration: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Static scheduling hints — PolicyEngine.authorize remains authoritative.
TOOL_SIDE_EFFECTS: dict[str, tuple[SideEffect, ...]] = {
    "read": ("workspace_read",),
    "grep": ("workspace_read",),
    "glob": ("workspace_read",),
    "ls": ("workspace_read",),
    "write": ("workspace_write",),
    "edit": ("workspace_write",),
    "apply_patch": ("workspace_write",),
    "bash": ("long_running", "workspace_write"),
    "web_search": ("network", "workspace_read"),
    "web_fetch": ("network", "workspace_read"),
    "task": ("nested_agent", "long_running"),
    "subagent": ("nested_agent", "long_running"),
    "memory": ("workspace_read",),
    "skill": ("workspace_read",),
    "memory_write": ("durable_memory",),
}


def side_effects_for(tool_name: str) -> tuple[SideEffect, ...]:
    """Default effects by tool name — use derive_effects(call) for authorization."""
    return TOOL_SIDE_EFFECTS.get(tool_name, ("workspace_read", "workspace_write"))
