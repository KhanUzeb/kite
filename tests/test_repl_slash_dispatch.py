"""REPL slash command dispatch (low cyclomatic complexity path)."""

from __future__ import annotations

import inspect
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


def test_handle_slash_restricted_on_off(session: ChatSession) -> None:
    assert session._handle_slash("/restricted on") is True
    assert session.state.sandbox_restricted is True
    assert session._execution_mode() == "restricted"
    assert session._handle_slash("/sandbox off") is True
    assert session.state.sandbox_restricted is False


def test_handle_slash_restricted_empty_picks(session: ChatSession) -> None:
    session._pick = lambda items, **kw: "on"  # type: ignore[method-assign]
    assert session._handle_slash("/restricted") is True
    assert session.state.sandbox_restricted is True


def test_handle_slash_approve_empty_picks(session: ChatSession) -> None:
    from kite.agent.mode import ApprovalMode

    session._pick = lambda items, **kw: "yolo"  # type: ignore[method-assign]
    assert session._handle_slash("/approve") is True
    assert session.state.approval is ApprovalMode.YOLO


def test_slash_models_provider_and_id_saves(session: ChatSession, kite_home) -> None:
    from kite.config import UserConfig

    applied: list[tuple[str, str]] = []
    session._apply_connected = lambda p, m: applied.append((p, m))  # type: ignore[method-assign]
    assert session._handle_slash("/models ollama llama3.2") is True
    assert applied == [("ollama", "llama3.2")]
    cfg = UserConfig.load()
    assert cfg.default_provider == "ollama"
    assert cfg.default_model == "llama3.2"


def test_zero_arg_slash_handlers_accept_empty_arg(session: ChatSession) -> None:
    handlers = session._slash_handlers()
    for name in ("compact", "keys", "clip", "attachments", "semantic", "episodic"):
        fn = handlers[name]
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        assert len(params) >= 1, f"/{name} handler must accept arg"
