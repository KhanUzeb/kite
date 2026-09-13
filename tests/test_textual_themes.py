"""Textual CSS themes from kite palettes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from kite.ui.textual.themes import _THEME_CSS_KEY, apply_theme_to_app, textual_css
from kite.ui.theme import reset_prefs


def test_textual_css_includes_accent() -> None:
    reset_prefs(theme="kite")
    css = textual_css("kite")
    assert "Composer" in css
    assert "#" in css


def test_apply_theme_to_app_without_stylesheet_clear() -> None:
    """Textual 8+ Stylesheet has no clear(); theme CSS replaces via stable read_from key."""
    app = MagicMock()
    app.stylesheet.add_source = MagicMock()
    app.refresh_css = MagicMock()

    name = apply_theme_to_app(app, "kite")

    assert name == "kite"
    app.stylesheet.add_source.assert_called_once()
    css_arg, kwargs = app.stylesheet.add_source.call_args
    assert "Composer" in css_arg[0]
    assert kwargs["read_from"] == _THEME_CSS_KEY
    app.refresh_css.assert_called_once_with(animate=False)
