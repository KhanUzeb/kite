"""CLI result contract and exit codes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any

from kite.application.contracts import RunResult


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
        if result.status == "completed":
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
