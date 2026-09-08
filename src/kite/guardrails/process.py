"""Process-group helpers for reliable subprocess teardown."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any


def popen_process_group_kwargs() -> dict[str, Any]:
    """Keyword args for ``Popen`` that isolate child processes in a new group."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(proc: subprocess.Popen[Any], *, grace_seconds: float = 0.25) -> None:
    """Terminate a process and its descendants (best effort)."""
    if proc.poll() is not None:
        return
    pid = proc.pid
    if pid is None:
        try:
            proc.kill()
        except OSError:
            pass
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        return

    try:
        pgid = os.getpgid(pid)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
        return

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
