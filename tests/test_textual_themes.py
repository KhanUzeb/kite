"""Textual CSS themes from kite palettes."""

from __future__ import annotations

from kite.ui.textual.themes import textual_css
from kite.ui.theme import reset_prefs


def test_textual_css_includes_accent() -> None:
    reset_prefs(theme="kite")
    css = textual_css("kite")
    assert "Composer" in css
    assert "#" in css
