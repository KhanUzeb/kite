"""Subprocess helpers for provider CLI delegation."""

from __future__ import annotations

import subprocess


def run_cli(
    command: str,
    *args: str,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a provider CLI with secrets kept out of exception messages."""
    return subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def run_checked(command: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    proc = run_cli(command, *args, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{command} exited with status {proc.returncode}")
    return proc
