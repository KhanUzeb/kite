"""Construct production ToolExecutor instances for the agent loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from kite.application.execution.pipeline import ToolExecutor
from kite.application.policy import PolicyEngine
from kite.application.tools.contracts import ToolCall
from kite.guardrails import redact_secrets


def build_tool_executor(
    *,
    workspace_root: str | Path,
    execution_mode: str,
    no_guardrails: bool,
    runner: Callable[[ToolCall], dict[str, Any]],
    policy_engine: PolicyEngine | None = None,
) -> ToolExecutor:
    policy = policy_engine or PolicyEngine(
        workspace_root,
        execution_mode=execution_mode,
        no_guardrails=no_guardrails,
    )
    return ToolExecutor(
        policy=policy,
        runner=runner,
        approver=None,
        redactor=lambda text: redact_secrets(text)[0],
    )
