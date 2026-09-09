"""REPL lazy init, harness cache, /jobs and /kill."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from kite.ui.repl import ChatSession

# --- lazy model resolve ---


def test_chat_session_init_skips_model_resolve(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    def _fake_resolve(**kwargs):
        calls.append(kwargs)
        raise AssertionError("resolve_model should not run during REPL init")

    monkeypatch.setattr("kite.providers.resolve.resolve_model", _fake_resolve)

    session = ChatSession(cwd=str(tmp_path))
    assert session.provider is not None or session.model is not None or True
    assert not calls


def test_ensure_model_resolved_on_first_task(monkeypatch, tmp_path) -> None:
    resolved = MagicMock()
    resolved.provider = "groq"
    resolved.model = "llama-test"
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: resolved)

    session = ChatSession(cwd=str(tmp_path))
    session._ensure_model_resolved()
    assert session.provider == "groq"
    assert session.model == "llama-test"
    assert session._model_resolved is True


def test_harness_reused_when_cache_key_matches(monkeypatch, tmp_path) -> None:
    resolved = MagicMock()
    resolved.provider = "groq"
    resolved.model = "llama-test"
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: resolved)

    session = ChatSession(cwd=str(tmp_path))
    session._ensure_model_resolved()
    first = session._make_harness()
    second = session._make_harness()
    assert first is second


# --- jobs slash ---


@dataclass
class _FakeJob:
    id: str
    kind: str = "bash"
    command: str = "sleep 1"
    label: str = ""
    pid: int | None = 4242
    status: str = "running"

    def display_label(self, *, width: int = 48) -> str:
        return (self.label or self.command)[:width]


class _FakeRegistry:
    def __init__(self, jobs: list[_FakeJob] | None = None) -> None:
        self._jobs = {j.id: j for j in (jobs or [])}
        self.killed: list[str] = []
        self.kill_all_calls = 0

    def list(self, *, active_only: bool = True) -> list[_FakeJob]:
        rows = [j for j in self._jobs.values() if j.status == "running"] if active_only else list(self._jobs.values())
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
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: MagicMock(provider="groq", model="test"))
    return ChatSession(cwd=str(tmp_path))


def test_slash_jobs_pick_kills(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="bash0001", command="npm run dev")])
    session.jobs = reg  # type: ignore[assignment]
    session._pick = lambda items, **kw: "bash0001"  # type: ignore[method-assign]
    assert session._handle_slash("/jobs") is True
    assert reg.killed == ["bash0001"]


def test_slash_kill_all(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="a1"), _FakeJob(id="b2", kind="subagent")])
    session.jobs = reg  # type: ignore[assignment]
    assert session._handle_slash("/kill all") is True
    assert set(reg.killed) == {"a1", "b2"}


def test_teardown_jobs_on_quit_path(session: ChatSession) -> None:
    reg = _FakeRegistry([_FakeJob(id="x1")])
    session.jobs = reg  # type: ignore[assignment]
    session._teardown_jobs()
    assert reg.kill_all_calls == 1


def test_prewarm_composer_primes_slash_index(tmp_path) -> None:
    from pathlib import Path

    from kite.cli.slash import _INDEX_CACHE

    _INDEX_CACHE.clear()
    session = ChatSession(cwd=str(tmp_path))
    session._prewarm_composer()
    key = (str(Path(tmp_path).resolve()), ())
    assert _INDEX_CACHE.get(key) is not None
    assert session._prompt is not None
