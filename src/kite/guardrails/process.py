"""Process-group helpers for reliable subprocess teardown."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def popen_process_group_kwargs() -> dict[str, Any]:
    """Keyword args for ``Popen`` that isolate child processes in a new group."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(proc: subprocess.Popen[Any], *, grace_seconds: float = 0.25) -> None:
    """Terminate a process and its descendants (best effort)."""
    if os.name == "nt" and proc.poll() is not None:
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
    except ProcessLookupError:
        # Isolated children use their pid as pgid. The leader may have exited
        # while descendants still hold its stdout pipe open.
        pgid = pid
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

    try:
        proc.wait(timeout=max(0.0, grace_seconds))
    except subprocess.TimeoutExpired:
        pass
    # Reap stubborn descendants even if their group leader exited on SIGTERM.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        pass
