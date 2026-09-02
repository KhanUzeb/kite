"""JobRegistry — bash spawn/list/kill and kill_all teardown."""

from __future__ import annotations

import sys
import time

import pytest

from kite.agent.cancel import CancelToken
from kite.tools.jobs import JobRegistry


def _sleep_cmd(seconds: float = 30) -> str:
    if sys.platform == "win32":
        # ping blocks ~1s per count; use python for portable long sleep
        return f'{sys.executable} -c "import time; time.sleep({seconds})"'
    return f"sleep {seconds}"


def test_spawn_list_kill_gone(tmp_path) -> None:
    reg = JobRegistry()
    job = reg.spawn_bash(_sleep_cmd(60), cwd=str(tmp_path))
    assert job.kind == "bash"
    assert job.status == "running"
    assert job.pid is not None
    active = reg.list(active_only=True)
    assert len(active) == 1
    assert active[0].id == job.id
    assert reg.kill(job.id) is True
    assert reg.get(job.id) is not None
    assert reg.get(job.id).status == "killed"  # type: ignore[union-attr]
    assert reg.list(active_only=True) == []
    # second kill is a no-op
    assert reg.kill(job.id) is False


def test_kill_all_on_close(tmp_path) -> None:
    reg = JobRegistry()
    a = reg.spawn_bash(_sleep_cmd(60), cwd=str(tmp_path))
    b = reg.spawn_bash(_sleep_cmd(60), cwd=str(tmp_path))
    assert reg.active_count() == 2
    n = reg.kill_all()
    assert n == 2
    assert reg.active_count() == 0
    assert a.status == "killed"
    assert b.status == "killed"
    assert reg.kill_all() == 0


def test_register_subagent_kill_cancels_token() -> None:
    reg = JobRegistry()
    token = CancelToken()
    job = reg.register_subagent(label="worker-1", prompt="do stuff", cancel=token)
    assert job.kind == "subagent"
    assert reg.active_count() == 1
    assert reg.kill(job.id) is True
    assert token.is_set()
    assert job.status == "killed"
    assert reg.list(active_only=True) == []


def test_job_events_emitted(tmp_path) -> None:
    events: list[str] = []
    reg = JobRegistry(on_event=lambda e: events.append(e.kind))
    job = reg.spawn_bash(
        f'{sys.executable} -c "print(1)"',
        cwd=str(tmp_path),
    )
    # wait briefly for short command to finish
    deadline = time.monotonic() + 5
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "job_start" in events
    assert "job_end" in events or reg.kill(job.id)


def test_mark_done_idempotent_after_kill() -> None:
    reg = JobRegistry()
    token = CancelToken()
    job = reg.register_subagent(job_id="abc12345", label="x", cancel=token)
    reg.kill(job.id)
    reg.mark_done(job.id, ok=False)  # should not resurrect
    assert job.status == "killed"
