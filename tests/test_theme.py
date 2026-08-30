"""Theme palettes and glyph packs."""

from __future__ import annotations

from kite.cli.slash import CommandIndex
from kite.ui.commands import ARG_CHOICES, CONTROL_COMMANDS
from kite.ui.complete import SlashCompleter
from kite.ui.status import context_meter
from kite.ui.theme import (
    FONT_NAMES,
    THEME_NAMES,
    current_font,
    glyph,
    palette,
    reset_prefs,
    resolved_theme,
    set_font,
    set_theme,
    theme_label,
)


def _reset() -> None:
    reset_prefs(theme="auto", font="unicode")


def test_builtin_theme_and_font_commands() -> None:
    assert "theme" in CONTROL_COMMANDS
    assert "font" in CONTROL_COMMANDS
    assert [row[0] for row in ARG_CHOICES["theme"]] == list(THEME_NAMES)
    assert [row[0] for row in ARG_CHOICES["font"]] == list(FONT_NAMES)


def test_theme_dropdown_lists_palettes() -> None:
    from kite.ui.complete import _PT

    if not _PT:
        return

    completer = SlashCompleter(lambda: CommandIndex())

    class _Doc:
        def __init__(self, text: str) -> None:
            self.text_before_cursor = text

    values = [c.text for c in completer.get_completions(_Doc("/theme "), None)]
    assert "kite" in values
    assert "light" in values
    assert "mono" in values


def test_auto_theme_resolves_to_a_palette() -> None:
    _reset()
    assert resolved_theme("auto") in {"kite", "light"}
    assert "auto" in theme_label()


def test_light_theme_uses_blue_brand() -> None:
    _reset()
    try:
        assert set_theme("light") == "light"
        assert palette()["styles"]["kite.brand"] == "blue"
        assert palette()["syntax"] == "ansi_light"
    finally:
        _reset()


def test_unknown_theme_is_rejected() -> None:
    _reset()
    assert set_theme("solarized") is None
    assert set_font("comic-sans") is None


def test_ascii_font_swaps_glyphs() -> None:
    _reset()
    try:
        assert glyph("ok") == "✓"
        assert set_font("ascii") == "ascii"
        assert current_font() == "ascii"
        assert glyph("ok") == "+"
        assert glyph("warn") == "!"
        assert glyph("prompt") == ">"
        meter = context_meter(0.5)
        assert "#" in meter
        assert "█" not in meter
    finally:
        _reset()


def test_font_alias_plain_is_ascii() -> None:
    _reset()
    try:
        assert set_font("plain") == "ascii"
    finally:
        _reset()


def test_prefs_persist_to_user_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KITE_HOME", str(tmp_path))
    _reset()
    try:
        set_theme("dim", persist=True)
        set_font("ascii", persist=True)
        from kite.config import UserConfig

        saved = UserConfig.load()
        assert saved.theme == "dim"
        assert saved.font == "ascii"
    finally:
        _reset()
