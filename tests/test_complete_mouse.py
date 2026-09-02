"""REPL composer mouse + clipboard + scroll completion settings."""

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


def test_prompt_session_disables_mouse_by_default(completer: SlashCompleter, monkeypatch) -> None:
    monkeypatch.delenv("KITE_MOUSE", raising=False)
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return MagicMock(mouse_support=kwargs.get("mouse_support"))

    monkeypatch.setattr("kite.ui.complete.PromptSession", fake_session)
    session = make_prompt_session(completer)
    if session is None:
        pytest.skip("prompt_toolkit unavailable")
    assert captured.get("mouse_support") is False
    assert captured.get("reserve_space_for_menu") == 8


def test_prompt_session_enables_mouse_when_kite_mouse(completer: SlashCompleter, monkeypatch) -> None:
    monkeypatch.setenv("KITE_MOUSE", "1")
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return MagicMock(mouse_support=kwargs.get("mouse_support"))

    monkeypatch.setattr("kite.ui.complete.PromptSession", fake_session)
    session = make_prompt_session(completer)
    if session is None:
        pytest.skip("prompt_toolkit unavailable")
    assert captured.get("mouse_support") is True


def test_repl_key_bindings_include_paste_copy_not_scroll_by_default(monkeypatch) -> None:
    monkeypatch.delenv("KITE_MOUSE", raising=False)
    bindings = make_repl_key_bindings()
    if bindings is None:
        pytest.skip("prompt_toolkit unavailable")
    keys: set[str] = set()
    for binding in bindings.bindings:
        keys.update(binding.keys)
    assert "c-v" in keys
    assert "s-insert" in keys
    assert "c-insert" in keys
    assert "<scroll-up>" not in keys
    assert "<scroll-down>" not in keys
    assert "c-p" in keys
    assert "c-b" in keys
    assert "f2" in keys
    assert "f3" in keys
    assert "f5" in keys
    assert "escape" in keys
    assert "c-g" in keys
    assert "c-s" not in keys
    assert "c-m" in keys
    assert any(b.eager() for b in bindings.bindings if "c-m" in b.keys)


def test_repl_key_bindings_scroll_when_kite_mouse(monkeypatch) -> None:
    monkeypatch.setenv("KITE_MOUSE", "1")
    bindings = make_repl_key_bindings(on_expand_thinking=lambda: None)
    if bindings is None:
        pytest.skip("prompt_toolkit unavailable")
    keys: set[str] = set()
    for binding in bindings.bindings:
        for k in binding.keys:
            keys.add(getattr(k, "value", str(k)))
    assert "<scroll-up>" in keys
    assert "<scroll-down>" in keys
    assert any("mouse-event" in k for k in keys)
