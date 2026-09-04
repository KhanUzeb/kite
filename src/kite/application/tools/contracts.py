"""Tool execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["ok", "error", "denied", "cancelled"]

SideEffect = Literal[
    "read",
    "workspace_write",
    "external_write",
    "sensitive_read",
    "network",
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
