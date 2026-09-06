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


def test_handle_slash_restricted_empty_picks(session: ChatSession) -> None:
    session._pick = lambda items, **kw: "on"  # type: ignore[method-assign]
    assert session._handle_slash("/restricted") is True
    assert session.state.sandbox_restricted is True


def test_handle_slash_approve_empty_picks(session: ChatSession) -> None:
    from kite.agent.mode import ApprovalMode

    session._pick = lambda items, **kw: "yolo"  # type: ignore[method-assign]
    assert session._handle_slash("/approve") is True
    assert session.state.approval is ApprovalMode.YOLO


def test_handle_slash_clear_alias(session: ChatSession) -> None:
    session._session_id = "test-session"
    assert session._handle_slash("/new") is True
    assert session._session_id is None


def test_handle_slash_stop_and_steer_idle(session: ChatSession) -> None:
    assert session._handle_slash("/stop") is True
    assert session._handle_slash("/steer") is True


def test_handle_slash_unknown(session: ChatSession, capsys) -> None:
    assert session._handle_slash("/not-a-real-cmd") is True
    captured = capsys.readouterr()
    text = (captured.out + captured.err).lower()
    assert "unknown" in text


def test_slash_models_two_providers_picks(session: ChatSession) -> None:
    seen: list = []

    def fake_pick(items, **_kw):
        seen.append(("pick", [item_id for item_id, _ in items]))
        return "chatgpt"

    def fake_connect(provider=None, **_kw):
        seen.append(("connect", provider))

    session._pick = fake_pick  # type: ignore[method-assign]
    session._connect_flow = fake_connect  # type: ignore[method-assign]
    assert session._handle_slash("/models ollama chatgpt") is True
    assert seen == [("pick", ["ollama", "chatgpt"]), ("connect", "chatgpt")]


def test_slash_models_one_provider_connects(session: ChatSession) -> None:
    seen: list = []
    session._connect_flow = lambda provider=None, **_kw: seen.append(provider)  # type: ignore[method-assign]
    assert session._handle_slash("/models ollama") is True
    assert seen == ["ollama"]


def test_slash_models_empty_connects(session: ChatSession) -> None:
    seen: list = []
    session._connect_flow = lambda provider=None, **_kw: seen.append(provider)  # type: ignore[method-assign]
    assert session._handle_slash("/models") is True
    assert seen == [None]


def test_slash_models_provider_and_id_saves(session: ChatSession, kite_home, monkeypatch) -> None:
    from kite.config import UserConfig

    applied: list[tuple[str, str]] = []
    session._apply_connected = lambda p, m: applied.append((p, m))  # type: ignore[method-assign]
    assert session._handle_slash("/models ollama llama3.2") is True
    assert applied == [("ollama", "llama3.2")]
    cfg = UserConfig.load()
    assert cfg.default_provider == "ollama"
    assert cfg.default_model == "llama3.2"
    assert cfg.provider_defaults.get("ollama") == "llama3.2"


def test_slash_models_refresh(session: ChatSession) -> None:
    seen: list = []
    session._refresh_models = lambda provider_arg="": seen.append(provider_arg)  # type: ignore[method-assign]
    assert session._handle_slash("/models refresh ollama") is True
    assert seen == ["ollama"]
    assert session._handle_slash("/refresh") is True
    assert seen[-1] == ""
    assert session._handle_slash("/model refresh groq") is True
    assert seen[-1] == "groq"


def test_slash_compact_accepts_dispatch_arg(session: ChatSession) -> None:
    """Slash dispatch always passes arg; /compact must not TypeError."""
    called: list[str] = []

    def fake_compact(arg: str = "") -> None:
        called.append(arg)

    session._compact_now = fake_compact  # type: ignore[method-assign]
    assert session._handle_slash("/compact") is True
    assert called == [""]


def test_zero_arg_slash_handlers_accept_empty_arg(session: ChatSession) -> None:
    """Handlers registered in _slash_handlers must accept the dispatch arg."""
    handlers = session._slash_handlers()
    for name in ("compact", "keys", "clip", "attachments", "semantic", "episodic"):
        fn = handlers[name]
        # Bound method or wrapper — must accept one str without TypeError.
        import inspect

        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        assert len(params) >= 1, f"/{name} handler {fn} must accept arg"
