"""REPL slash command dispatch (low cyclomatic complexity path)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kite.ui.repl import ChatSession


@pytest.fixture
def session(monkeypatch, tmp_path) -> ChatSession:
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    return ChatSession(cwd=str(tmp_path))


def test_handle_slash_quit_returns_false(session: ChatSession) -> None:
    assert session._handle_slash("/quit") is False


def test_handle_slash_plan(session: ChatSession) -> None:
    assert session._handle_slash("/plan") is True
    from kite.agent.mode import AgentMode, ApprovalMode

    assert session.state.mode is AgentMode.PLAN
    assert session.state.approval is ApprovalMode.READONLY


def test_handle_slash_restricted_default_off(session: ChatSession) -> None:
    assert session.state.sandbox_restricted is False
    assert session._execution_mode() == "host"


def test_handle_slash_restricted_on_off(session: ChatSession) -> None:
    assert session._handle_slash("/restricted on") is True
    assert session.state.sandbox_restricted is True
    assert session._execution_mode() == "restricted"
    assert session._handle_slash("/sandbox off") is True
    assert session.state.sandbox_restricted is False
    assert session._execution_mode() == "host"


def test_handle_slash_clear_alias(session: ChatSession) -> None:
    session._session_id = "test-session"
    assert session._handle_slash("/new") is True
    assert session._session_id is None


def test_handle_slash_unknown(session: ChatSession, capsys) -> None:
    assert session._handle_slash("/not-a-real-cmd") is True
    captured = capsys.readouterr()
    text = (captured.out + captured.err).lower()
    assert "unknown" in text
