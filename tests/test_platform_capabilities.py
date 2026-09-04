"""Platform and model capability tests."""

from __future__ import annotations

from kite.providers.capabilities import agent_model_warning, platform_shell_hint


def test_embedding_model_warns() -> None:
    warning = agent_model_warning("text-embedding-3-small")
    assert warning is not None
    assert "tool" in warning.lower()


def test_agent_model_no_warning() -> None:
    assert agent_model_warning("claude-sonnet-4") is None


def test_platform_hint_windows(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    hint = platform_shell_hint()
    assert "Windows" in hint


def test_platform_hint_posix(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    hint = platform_shell_hint()
    assert "POSIX" in hint
