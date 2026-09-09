"""Compatibility adapters between 0.8 harness config and 0.9 RunSpec."""

from __future__ import annotations

from pathlib import Path

from kite.agent.harness import HarnessConfig
from kite.application.contracts import ModelSelection, RunLimits, RunSpec


def run_spec_from_harness_config(config: HarnessConfig, task: str, *, workspace: Path | None = None) -> RunSpec:
    """Convert legacy ``HarnessConfig`` into a canonical ``RunSpec``."""
    cwd = Path(config.cwd or ".").expanduser().resolve()
    return RunSpec(
        task=task,
        workspace=workspace or cwd,
        session_id=config.session_id,
        parent_run_id=None,
        execution_mode=config.execution_mode,
        mode=config.mode,
        approval_mode=config.approval,
        limits=RunLimits(
            step_limit=config.step_limit,
            cost_limit=config.cost_limit,
            wall_time_limit_seconds=config.wall_time_limit_seconds or None,
        ),
        model_selection=ModelSelection(
            provider=config.provider,
            model_name=config.model_name,
            reasoning=config.reasoning,
        ),
        resume=config.resume,
        follow_up=config.follow_up,
        label=config.label,
        no_context=config.no_context,
        no_compact=config.no_compact,
        no_guardrails=config.no_guardrails,
        no_extensions=config.no_extensions,
        interactive=config.interactive,
        role=config.role,
        long_task=config.long_task,
        memory_in_prompt=config.memory_in_prompt,
        system_prompt=config.system_prompt,
        config_name=config.config_name,
        output_path=config.output_path,
        attachments=config.attachments,
    )


def harness_config_from_run_spec(spec: RunSpec) -> HarnessConfig:
    """Convert canonical ``RunSpec`` back to legacy ``HarnessConfig``."""
    return HarnessConfig(
        provider=spec.model_selection.provider,
        model_name=spec.model_selection.model_name,
        cwd=str(spec.workspace),
        step_limit=spec.limits.step_limit,
        cost_limit=spec.limits.cost_limit,
        wall_time_limit_seconds=spec.limits.wall_time_limit_seconds or 0,
        output_path=spec.output_path,
        system_prompt=spec.system_prompt,
        session_id=spec.session_id,
        resume=spec.resume,
        follow_up=spec.follow_up,
        label=spec.label,
        no_context=spec.no_context,
        no_compact=spec.no_compact,
        no_guardrails=spec.no_guardrails,
        no_extensions=spec.no_extensions,
        config_name=spec.config_name,
        mode=spec.mode,
        approval=spec.approval_mode,
        interactive=spec.interactive,
        reasoning=spec.model_selection.reasoning,
        role=spec.role,
        attachments=spec.attachments,
        execution_mode=spec.execution_mode,
        long_task=spec.long_task,
        memory_in_prompt=spec.memory_in_prompt,
    )
