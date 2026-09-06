"""Shared application-layer run execution for CLI and REPL."""

from __future__ import annotations

from typing import Any

from kite.agent.harness import Harness
from kite.application.adapters.harness import run_spec_from_harness_config
from kite.application.contracts import RunResult, RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.service import ApplicationRunService


def build_run_spec(harness: Harness, task: str) -> RunSpec:
    """Build a canonical RunSpec from a wired harness and task string."""
    return run_spec_from_harness_config(harness.config, task)


def execute_run(
    spec: RunSpec,
    harness: Harness,
    *,
    deps: HarnessDependencies | None = None,
    cancel: Any = None,
) -> RunResult:
    """Production entry — routes through ApplicationRunService."""
    service = ApplicationRunService()
    return service.run(spec, deps=deps or HarnessDependencies(), harness=harness, cancel=cancel)


def execute_harness_task(
    harness: Harness,
    task: str,
    *,
    deps: HarnessDependencies | None = None,
    cancel: Any = None,
) -> RunResult:
    """Convenience: build RunSpec from harness config and execute."""
    spec = build_run_spec(harness, task)
    return execute_run(spec, harness, deps=deps, cancel=cancel)


def legacy_result_from_run(result: RunResult) -> dict[str, Any]:
    """Project RunResult to the legacy dict shape callers still consume."""
    legacy = dict(result.legacy)
    if result.final_message and "submission" not in legacy:
        legacy["submission"] = result.final_message
    if result.verification:
        legacy["verification"] = result.verification
    if result.changed_paths and "changed_paths" not in legacy:
        legacy["changed_paths"] = list(result.changed_paths)
    if result.verification_status:
        legacy["verification_status"] = result.verification_status
    return legacy
