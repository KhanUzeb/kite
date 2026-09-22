"""Subprocess helpers for provider CLI delegation."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable


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


def run_cli_streaming(
    command: str,
    *args: str,
    timeout: float = 60.0,
    on_line: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a provider CLI, delivering stdout+stderr lines as they arrive.

    Used by OAuth logins that must surface a sign-in URL before the child
    exits (a fully captured run would hide the URL until it is too late).
    """
    proc = subprocess.Popen(
        [command, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    chunks: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:
                    pass

    worker = threading.Thread(target=_reader, daemon=True)
    worker.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        worker.join(timeout=1.0)
        raise
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        worker.join(timeout=1.0)
        raise
    worker.join(timeout=1.0)
    out = "".join(chunks)
    return subprocess.CompletedProcess([command, *args], proc.returncode, out, "")
