"""Process execution adapter."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from kite.guardrails.env_filter import filtered_child_env
from kite.guardrails.process import popen_process_group_kwargs, terminate_process_tree


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    truncated: bool = False
    cancelled: bool = False


class ProcessRunner:
    """Cross-platform subprocess runner with timeout and output limits."""

    def __init__(self, *, timeout_seconds: float = 120.0, max_output_bytes: int = 256_000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(self, command: list[str] | str, *, cwd: str | None = None, shell: bool = False) -> ProcessResult:
        env = filtered_child_env()
        start = time.monotonic()
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **popen_process_group_kwargs(),
        )
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            return ProcessResult(-1, stdout or "", stderr or "timeout", time.monotonic() - start)
        except Exception as exc:
            terminate_process_tree(proc)
            return ProcessResult(-1, "", str(exc), time.monotonic() - start)
        stdout, stderr, truncated = stdout or "", stderr or "", False
        if len(stdout.encode()) > self.max_output_bytes:
            stdout = stdout[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        if len(stderr.encode()) > self.max_output_bytes:
            stderr = stderr[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        return ProcessResult(int(proc.returncode or 0), stdout, stderr, time.monotonic() - start, truncated)
