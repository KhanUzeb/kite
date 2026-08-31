"""REPL composer mouse + scroll completion settings."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kite.ui.complete import SlashCompleter, make_prompt_session, make_repl_key_bindings


@pytest.fixture
def completer() -> SlashCompleter:
    return SlashCompleter(
        index_factory=lambda: MagicMock(specs={}, skills=[], plugins=[]),
        models_factory=lambda: [],
        providers_factory=lambda: [],
    )


def test_prompt_session_enables_mouse_support(completer: SlashCompleter, monkeypatch) -> None:
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return MagicMock(mouse_support=kwargs.get("mouse_support"))

    monkeypatch.setattr("kite.ui.complete.PromptSession", fake_session)
    session = make_prompt_session(completer)
    if session is None:
        pytest.skip("prompt_toolkit unavailable")
    assert captured.get("mouse_support") is True
    assert captured.get("reserve_space_for_menu") == 8


def test_repl_key_bindings_include_scroll() -> None:
    bindings = make_repl_key_bindings()
    if bindings is None:
        pytest.skip("prompt_toolkit unavailable")
    keys: set[str] = set()
    for binding in bindings.bindings:
        keys.update(binding.keys)
    assert "<scroll-up>" in keys
    assert "<scroll-down>" in keys
