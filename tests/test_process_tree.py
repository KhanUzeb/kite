"""Process-tree termination on timeout/cancel."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from kite.application.execution.process_runner import ProcessRunner
from kite.guardrails.process import popen_process_group_kwargs, terminate_process_tree


def _child_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.mark.skipif(os.name == "nt", reason="posix process-group test")
def test_terminate_process_tree_kills_descendants(tmp_path) -> None:
    marker = tmp_path / "child.pid"
    parent_script = f"""
import subprocess, sys, time, os
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
)
open({repr(str(marker))}, "w", encoding="utf-8").write(str(child.pid))
time.sleep(120)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_process_group_kwargs(),
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not marker.is_file():
        time.sleep(0.05)
    assert marker.is_file(), "child pid marker not written"
    child_pid = int(marker.read_text(encoding="utf-8").strip())
    terminate_process_tree(proc)
    proc.wait(timeout=5)
    time.sleep(0.2)
    assert proc.poll() is not None
    assert not _child_pid_running(child_pid)


@pytest.mark.skipif(os.name == "nt", reason="posix process-group test")
def test_process_runner_timeout_kills_child(tmp_path) -> None:
    marker = tmp_path / "grandchild.pid"
    command = (
        f"{sys.executable} -c \"import subprocess, sys, time; "
        f"c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        f"open({repr(str(marker))},'w').write(str(c.pid)); time.sleep(120)\""
    )
    runner = ProcessRunner(timeout_seconds=1.0)
    result = runner.run(command, shell=True)
    assert result.exit_code == -1
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not marker.is_file():
        time.sleep(0.05)
    if marker.is_file():
        child_pid = int(marker.read_text(encoding="utf-8").strip())
        assert not _child_pid_running(child_pid)
