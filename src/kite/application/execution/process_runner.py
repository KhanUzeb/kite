"""Process execution adapter."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    truncated: bool = False
    cancelled: bool = False


_DROP_ENV = frozenset({"AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"})


class ProcessRunner:
    """Cross-platform subprocess runner with timeout and output limits."""

    def __init__(self, *, timeout_seconds: float = 120.0, max_output_bytes: int = 256_000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(self, command: list[str] | str, *, cwd: str | None = None, shell: bool = False) -> ProcessResult:
        env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
        start = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                shell=shell,
                capture_output=True,
                text=True,
                env=env,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(-1, "", "timeout", time.monotonic() - start)
        except Exception as exc:
            return ProcessResult(-1, "", str(exc), time.monotonic() - start)
        stdout, stderr, truncated = completed.stdout, completed.stderr, False
        if len(stdout.encode()) > self.max_output_bytes:
            stdout = stdout[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        if len(stderr.encode()) > self.max_output_bytes:
            stderr = stderr[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        return ProcessResult(int(completed.returncode or 0), stdout, stderr, time.monotonic() - start, truncated)
