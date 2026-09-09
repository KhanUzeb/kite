"""Central harness config builder — one shape for CLI, REPL, headless, and nested workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kite.agent.harness import HarnessConfig


def build_harness_config(
    *,
    provider: str | None = None,
    model_name: str | None = None,
    cwd: str | None = None,
    step_limit: int | None = None,
    cost_limit: float | None = None,
    wall_time_limit_seconds: int = 0,
    output_path: Path | None = None,
    system_prompt: str | None = None,
    session_id: str | None = None,
    resume: bool = False,
    follow_up: str | None = None,
    label: str = "",
    no_context: bool = False,
    no_compact: bool = False,
    no_guardrails: bool = False,
    no_extensions: bool = False,
    config_name: str | Path | None = None,
    mode: str = "build",
    approval: str = "auto",
    interactive: bool = False,
    reasoning: str = "auto",
    role: str = "auto",
    attachments: list | None = None,
    execution_mode: str | None = None,
    long_task: bool = False,
    memory_in_prompt: bool = False,
    **extra: Any,
) -> HarnessConfig:
    """Build ``HarnessConfig`` for any harness entry point."""
    if extra:
        known = {f.name for f in HarnessConfig.__dataclass_fields__.values()}
        unknown = sorted(k for k in extra if k not in known)
        if unknown:
            raise TypeError(f"unknown harness config field(s): {', '.join(unknown)}")
    return HarnessConfig(
        provider=provider,
        model_name=model_name,
        cwd=cwd,
        step_limit=step_limit,
        cost_limit=cost_limit,
        wall_time_limit_seconds=wall_time_limit_seconds,
        output_path=output_path,
        system_prompt=system_prompt,
        session_id=session_id,
        resume=resume,
        follow_up=follow_up,
        label=label,
        no_context=no_context,
        no_compact=no_compact,
        no_guardrails=no_guardrails,
        no_extensions=no_extensions,
        config_name=config_name,
        mode=mode,
        approval=approval,
        interactive=interactive,
        reasoning=reasoning,
        role=role,
        attachments=attachments,
        execution_mode=execution_mode,
        long_task=long_task,
        memory_in_prompt=memory_in_prompt,
        **extra,
    )
