"""Slash /jobs and /kill dispatch with mock JobRegistry."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from kite.ui.repl import ChatSession


@dataclass
class _FakeJob:
    id: str
    kind: str = "bash"
    command: str = "sleep 1"
    label: str = ""
    pid: int | None = 4242
    status: str = "running"

    def display_label(self, *, width: int = 48) -> str:
        text = self.label or self.command
        return text[:width]


class _FakeRegistry:
    def __init__(self, jobs: list[_FakeJob] | None = None) -> None:
        self._jobs = {j.id: j for j in (jobs or [])}
        self.killed: list[str] = []
        self.kill_all_calls = 0

    def list(self, *, active_only: bool = True) -> list[_FakeJob]:
        rows = list(self._jobs.values())
        if active_only:
            rows = [j for j in rows if j.status == "running"]
        return rows

    def active_count(self) -> int:
        return len(self.list(active_only=True))

    def kill(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status != "running":
            return False
        job.status = "killed"
        self.killed.append(job_id)
        return True

    def kill_all(self) -> int:
        self.kill_all_calls += 1
        n = 0
        for job in self._jobs.values():
            if job.status == "running":
                job.status = "killed"
                self.killed.append(job.id)
                n += 1
        return n


@pytest.fixture
def session(monkeypatch, tmp_path) -> ChatSession:
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    return ChatSession(cwd=str(tmp_path))


def test_slash_jobs_empty(session: ChatSession) -> None:
    session.jobs = _FakeRegistry()  # type: ignore[assignment]
    assert session._handle_slash("/jobs") is True


def test_slash_jobs_pick_kills(session: ChatSession) -> None:
    reg = _FakeRegistry(
        [
            _FakeJob(id="bash0001", kind="bash", command="npm run dev"),
            _FakeJob(id="sub00002", kind="subagent", label="plan item", pid=None),
        ]
    )
    session.jobs = reg  # type: ignore[assignment]
    session._pick = lambda items, **kw: "bash0001"  # type: ignore[method-assign]
    assert session._handle_slash("/jobs") is True
    assert reg.killed == ["bash0001"]


def test_slash_kill_all(session: ChatSession) -> None:
    reg = _FakeRegistry(
        [
            _FakeJob(id="a1"),
            _FakeJob(id="b2", kind="subagent", label="worker", pid=None),
        ]
    )
    session.jobs = reg  # type: ignore[assignment]
    assert session._handle_slash("/kill all") is True
    assert set(reg.killed) == {"a1", "b2"}
    assert reg.kill_all_calls == 1


def test_slash_kill_by_id(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="deadbeef", command="uvicorn app:main")])
    session.jobs = reg  # type: ignore[assignment]
    assert session._handle_slash("/kill deadbeef") is True
    assert reg.killed == ["deadbeef"]


def test_slash_kill_missing(session: ChatSession, capsys) -> None:
    session.jobs = _FakeRegistry()  # type: ignore[assignment]
    assert session._handle_slash("/kill nope") is True


def test_slash_kill_empty_picks(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="pickme")])
    session.jobs = reg  # type: ignore[assignment]
    session._pick = lambda items, **kw: "pickme"  # type: ignore[method-assign]
    assert session._handle_slash("/kill") is True
    assert reg.killed == ["pickme"]


def test_teardown_jobs_on_quit_path(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="x1"), _FakeJob(id="x2")])
    session.jobs = reg  # type: ignore[assignment]
    session._teardown_jobs()
    assert reg.kill_all_calls == 1
    assert set(reg.killed) == {"x1", "x2"}


def test_jobs_and_kill_registered_as_builtins() -> None:
    from kite.ui.commands import ARG_CHOICES, CONTROL_COMMANDS

    assert "jobs" in CONTROL_COMMANDS
    assert "kill" in CONTROL_COMMANDS
    assert ARG_CHOICES["kill"][0][0] == "all"
