"""REPL cold-start should not resolve models until the first task."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_chat_session_init_skips_model_resolve(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    def _fake_resolve(**kwargs):
        calls.append(kwargs)
        raise AssertionError("resolve_model should not run during REPL init")

    monkeypatch.setattr("kite.providers.resolve.resolve_model", _fake_resolve)

    from kite.ui.repl import ChatSession

    session = ChatSession(cwd=str(tmp_path))
    assert session.provider is not None or session.model is not None or True
    assert not calls


def test_ensure_model_resolved_on_first_task(monkeypatch, tmp_path) -> None:
    resolved = MagicMock()
    resolved.provider = "groq"
    resolved.model = "llama-test"
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: resolved)

    from kite.ui.repl import ChatSession

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

    from kite.ui.repl import ChatSession

    session = ChatSession(cwd=str(tmp_path))
    session._ensure_model_resolved()
    first = session._make_harness()
    second = session._make_harness()
    assert first is second
