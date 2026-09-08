"""Theme palettes, aliases, and TUI color wiring."""

from __future__ import annotations

import pytest

from kite.ui.theme import (
    THEME_NAMES,
    brand_fg,
    palette,
    pt_style_dict,
    reset_prefs,
    resolved_theme,
    rich_theme,
    set_theme,
    ui_colors,
)


@pytest.fixture(autouse=True)
def _pin_prefs() -> None:
    reset_prefs(theme="auto", font="unicode")
    yield
    reset_prefs(theme="auto", font="unicode")


def test_new_themes_are_registered() -> None:
    for name in ("monochrome", "catppuccin", "ember", "forest", "hues"):
        assert name in THEME_NAMES
        assert "kite.brand" in palette(name)["styles"]


def test_theme_aliases_resolve() -> None:
    assert set_theme("catpuccin") == "catppuccin"
    assert set_theme("green-forest") == "forest"
    assert resolved_theme("catpuccin") == "catppuccin"


def test_palettes_have_distinct_brand_colors() -> None:
    brands = {name: brand_fg(name) for name in ("kite", "catppuccin", "ember", "forest", "hues")}
    assert len(set(brands.values())) == len(brands)


def test_ui_colors_change_per_theme() -> None:
    kite_ui = ui_colors("kite")
    forest_ui = ui_colors("forest")
    assert kite_ui.accent != forest_ui.accent
    assert kite_ui.toolbar_bg != forest_ui.toolbar_bg


def test_pt_style_dict_uses_theme_ui() -> None:
    reset_prefs(theme="catppuccin")
    styles = pt_style_dict()
    ui = ui_colors("catppuccin")
    assert ui.prompt in styles["prompt"]
    assert ui.toolbar_bg in styles["bottom-toolbar"]


def test_rich_theme_styles_differ_for_ember_and_forest() -> None:
    ember = rich_theme("ember").styles["kite.brand"]
    forest = rich_theme("forest").styles["kite.brand"]
    assert ember != forest


def test_default_glyphs_are_plain_symbols() -> None:
    from kite.ui.theme import FONTS, glyph

    assert glyph("ok") == "+"
    assert glyph("warn") == "!"
    assert glyph("spin") == "*"
    assert all(ord(c) < 128 for pack in FONTS.values() for ch in pack.values() if ch for c in ch)


def test_monochrome_is_grayscale_rich_styles() -> None:
    styles = rich_theme("monochrome").styles
    brand = str(styles["kite.brand"])
    assert "#" in brand
    assert str(styles["kite.success"]) != "bold bright_green"
