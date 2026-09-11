"""Application CLI run helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from kite.application.adapters import run_spec_from_harness_config
from kite.application.contracts import RunResult, RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.service import ApplicationRunService

if TYPE_CHECKING:
    from kite.agent.harness import Harness


class ExitCode(IntEnum):
    SUCCESS = 0
    FAILURE = 1
    CANCELLED = 2
    APPROVAL_DENIED = 3
    VERIFICATION_FAILED = 4
    PARTIAL_APPLY = 5
    INVALID_CONFIG = 6


@dataclass(frozen=True, slots=True)
class CliResult:
    ok: bool
    exit_code: int
    status: str
    message: str
    run_id: str | None = None
    data: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @staticmethod
    def from_run_result(result: RunResult, *, run_id: str | None = None) -> CliResult:
        stop = result.stop_reason or ""
        if stop == "submitted" and result.status == "completed":
            return CliResult(True, ExitCode.SUCCESS, result.status, result.final_message, run_id, result.legacy)
        if stop == "cancelled" or stop == "interrupted":
            return CliResult(False, ExitCode.CANCELLED, result.status, result.final_message, run_id)
        if stop == "approval_denied":
            return CliResult(False, ExitCode.APPROVAL_DENIED, result.status, result.final_message, run_id)
        if stop == "verification_failed":
            return CliResult(False, ExitCode.VERIFICATION_FAILED, result.status, result.final_message, run_id)
        return CliResult(False, ExitCode.FAILURE, result.status, result.final_message or stop, run_id, result.legacy)


def format_cli_output(result: CliResult, *, json_mode: bool = False) -> str:
    if json_mode:
        return result.to_json()
    prefix = "OK" if result.ok else "ERROR"
    return f"{prefix}: {result.message}"





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
