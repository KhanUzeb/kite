"""Canonical run contracts — stable seams for CLI, REPL, and cloud adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

RunStatus = Literal[
    "created",
    "prepared",
    "awaiting_model",
    "awaiting_approval",
    "executing_tools",
    "observing",
    "compacting",
    "completed",
    "failed",
    "cancelled",
]

StopReason = Literal[
    "submitted",
    "error",
    "cancelled",
    "limits_exceeded",
    "approval_denied",
    "verification_failed",
    "stalled",
    "interrupted",
]


@dataclass(frozen=True, slots=True)
class RunLimits:
    step_limit: int | None = None
    cost_limit: float | None = None
    wall_time_limit_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ModelSelection:
    provider: str | None = None
    model_name: str | None = None
    reasoning: str = "auto"


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Immutable description of one harness run."""

    task: str
    workspace: Path
    run_id: str | None = None
    parent_run_id: str | None = None
    execution_mode: str | None = None  # restricted | host
    mode: str = "build"
    approval_mode: str = "auto"
    limits: RunLimits = field(default_factory=RunLimits)
    model_selection: ModelSelection = field(default_factory=ModelSelection)
    session_id: str | None = None
    resume: bool = False
    follow_up: str | None = None
    label: str = ""
    no_context: bool = False
    no_compact: bool = False
    no_guardrails: bool = False
    no_extensions: bool = False
    interactive: bool = False
    role: str = "auto"
    long_task: bool = False
    system_prompt: str | None = None
    config_name: str | Path | None = None
    output_path: Path | None = None
    attachments: list[Any] | None = None
    effective_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    stop_reason: StopReason | None = None
    final_message: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    verification_status: str = ""
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    approval_reason: str = ""
    blocked_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    changed_paths: tuple[str, ...] = ()
    context_snapshot_id: str | None = None
    trace_id: str | None = None
    legacy: dict[str, Any] = field(default_factory=dict)
