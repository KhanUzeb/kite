"""Process execution adapter."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


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

    def __init__(
        self,
        *,
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 256_000,
        env_sanitizer: Callable[[dict[str, str]], dict[str, str]] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self._sanitize = env_sanitizer or _default_sanitize

    def run(
        self,
        command: list[str] | str,
        *,
        cwd: str | None = None,
        shell: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ProcessResult:
        env = self._sanitize(dict(os.environ))
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            deadline = start + self.timeout_seconds
            while proc.poll() is None:
                if cancel_check and cancel_check():
                    proc.kill()
                    proc.wait(timeout=5)
                    return ProcessResult(
                        exit_code=-1,
                        stdout="",
                        stderr="cancelled",
                        duration=time.monotonic() - start,
                        cancelled=True,
                    )
                if time.monotonic() > deadline:
                    proc.kill()
                    proc.wait(timeout=5)
                    return ProcessResult(
                        exit_code=-1,
                        stdout="",
                        stderr="timeout",
                        duration=time.monotonic() - start,
                    )
                time.sleep(0.05)
            stdout, stderr = proc.communicate(timeout=1)
            truncated = False
            if len(stdout.encode()) > self.max_output_bytes:
                stdout = stdout[: self.max_output_bytes] + "\n...[truncated]"
                truncated = True
            if len(stderr.encode()) > self.max_output_bytes:
                stderr = stderr[: self.max_output_bytes] + "\n...[truncated]"
                truncated = True
            return ProcessResult(
                exit_code=int(proc.returncode or 0),
                stdout=stdout,
                stderr=stderr,
                duration=time.monotonic() - start,
                truncated=truncated,
            )
        except Exception as exc:
            return ProcessResult(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration=time.monotonic() - start,
            )


def _default_sanitize(env: dict[str, str]) -> dict[str, str]:
    drop = {"AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"}
    return {k: v for k, v in env.items() if k not in drop}
