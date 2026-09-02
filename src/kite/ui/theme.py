"""Terminal palettes and glyph packs — /theme and /font.

A CLI cannot change the host typeface. `font` here is the glyph pack
(unicode vs ascii) so broken terminals still read cleanly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich.theme import Theme

THEME_NAMES = ("auto", "kite", "dark", "light", "dim", "mono")
FONT_NAMES = ("unicode", "ascii")

THEME_HELP = {
    "auto": "follow the terminal (COLORFGBG)",
    "kite": "bright cyan brand on dark",
    "dark": "near-black UI, bright cyan accents",
    "light": "blue brand on light terminals",
    "dim": "low-contrast",
    "mono": "no color, bold errors only",
}

FONT_HELP = {
    "unicode": "✓ ⚠ › — default",
    "ascii": "+ ! > — for terminals that chew glyphs",
}

_KITE_STYLES = {
    "kite.brand": "bold cyan",
    "kite.thinking": "italic #6a6a6a",
    "kite.reasoning": "italic #6a6a6a",
    "kite.answer": "default",
    "kite.assistant": "default",
    "kite.user": "default",
    "kite.success": "bold bright_green",
    "kite.pending": "bold bright_yellow",
    "kite.error": "bold bright_red",
    "kite.muted": "#6e6e6e",
    "kite.tool": "bright_cyan",
    "kite.diff.add": "bold bright_green",
    "kite.diff.del": "bold bright_red",
    "kite.diff.hunk": "bold bright_cyan",
    "kite.diff.meta": "#5a5a5a",
    "kite.diff.ctx": "#7a7a7a",
    "kite.plan": "bold yellow",
    "kite.build": "bold green",
    "kite.accent": "bold magenta",
    "kite.highlight": "bold bright_cyan",
    "kite.task": "bold magenta",
    "kite.task.done": "bright_green",
    "kite.task.active": "bold bright_cyan",
    "kite.task.pending": "#5a7aaa",
    "kite.task.bar": "bright_green",
    "kite.task.bar_empty": "#3a3a3a",
    "kite.pick": "bright_cyan",
    "kite.pick.current": "bold bright_green",
}


def _styles(**overrides: str) -> dict[str, str]:
    out = dict(_KITE_STYLES)
    out.update(overrides)
    return out


_PALETTES: dict[str, dict[str, Any]] = {
    "kite": {
        "styles": _styles(),
        "dark": True,
        "syntax": "ansi_dark",
        "brand_ansi": "ansibrightcyan",
    },
    "dark": {
        "styles": _styles(
            **{
                "kite.brand": "bold bright_cyan",
                "kite.muted": "#555555",
                "kite.thinking": "italic #555555",
                "kite.reasoning": "italic #555555",
                "kite.diff.meta": "#444444",
                "kite.diff.ctx": "#666666",
            }
        ),
        "dark": True,
        "syntax": "ansi_dark",
        "brand_ansi": "ansibrightcyan",
    },
    "light": {
        "styles": _styles(
            **{
                "kite.brand": "bold blue",
                "kite.thinking": "italic #555555",
                "kite.reasoning": "italic #555555",
                "kite.tool": "blue",
                "kite.diff.add": "bold dark_green",
                "kite.diff.del": "bold dark_red",
                "kite.diff.hunk": "bold blue",
                "kite.diff.meta": "#666666",
                "kite.diff.ctx": "#777777",
                "kite.muted": "#666666",
                "kite.plan": "dark_goldenrod",
                "kite.build": "dark_green",
                "kite.success": "bold dark_green",
                "kite.pending": "bold dark_goldenrod",
                "kite.pick": "blue",
                "kite.pick.current": "bold dark_green",
            }
        ),
        "dark": False,
        "syntax": "ansi_light",
        "brand_ansi": "ansiblue",
    },
    "dim": {
        "styles": _styles(
            **{
                "kite.brand": "dim cyan",
                "kite.success": "dim green",
                "kite.pending": "dim yellow",
                "kite.error": "red",
                "kite.tool": "dim cyan",
                "kite.plan": "dim yellow",
                "kite.build": "dim green",
                "kite.diff.add": "green",
                "kite.diff.del": "red",
                "kite.diff.hunk": "cyan",
                "kite.pick": "dim cyan",
                "kite.pick.current": "green",
            }
        ),
        "dark": True,
        "syntax": "ansi_dark",
        "brand_ansi": "ansicyan",
    },
    "mono": {
        "styles": _styles(
            **{
                "kite.brand": "bold",
                "kite.thinking": "italic dim",
                "kite.reasoning": "italic dim",
                "kite.success": "default",
                "kite.pending": "default",
                "kite.error": "bold",
                "kite.muted": "dim",
                "kite.tool": "default",
                "kite.diff.add": "bold",
                "kite.diff.del": "dim",
                "kite.diff.hunk": "bold",
                "kite.diff.meta": "dim",
                "kite.diff.ctx": "dim",
                "kite.plan": "default",
                "kite.build": "bold",
                "kite.pick": "default",
                "kite.pick.current": "bold",
            }
        ),
        "dark": True,
        "syntax": "ansi_dark",
        "brand_ansi": "ansiwhite",
    },
}

_UNICODE = {
    "ok": "✓",
    "fail": "✗",
    "warn": "⚠",
    "spin": "●",
    "todo": "○",
    "collapse": "▸",
    "expand": "▾",
    "tool": "▸",
    "prompt": "›",
    "user": "›",
    "agent": "•",
    "compact": "↻",
    "sep": "·",
    "reason": "…",
    "bar_fill": "█",
    "bar_empty": "░",
    "chip_l": "╭ ",
    "chip_r": " ╮",
    "home": "~",
}

_ASCII = {
    "ok": "+",
    "fail": "x",
    "warn": "!",
    "spin": "*",
    "todo": "o",
    "collapse": ">",
    "expand": "v",
    "tool": ">",
    "prompt": ">",
    "user": ">",
    "agent": ".",
    "compact": "~",
    "sep": "|",
    "reason": "...",
    "bar_fill": "#",
    "bar_empty": "-",
    "chip_l": "[ ",
    "chip_r": " ]",
    "home": "~",
}

FONTS: dict[str, dict[str, str]] = {"unicode": _UNICODE, "ascii": _ASCII}


@dataclass
class UiPrefs:
    theme: str = "auto"
    font: str = "unicode"


_prefs = UiPrefs()
_loaded = False


def terminal_is_light() -> bool:
    colorfgbg = os.environ.get("COLORFGBG", "")
    if ";" in colorfgbg:
        try:
            return int(colorfgbg.split(";")[-1]) >= 8
        except ValueError:
            pass
    return False


def current_theme() -> str:
    return _prefs.theme


def current_font() -> str:
    return _prefs.font


def resolved_theme(name: str | None = None) -> str:
    raw = (name or _prefs.theme or "auto").strip().lower()
    if raw == "auto":
        return "light" if terminal_is_light() else "kite"
    if raw in _PALETTES:
        return raw
    return "kite"


def theme_label(name: str | None = None) -> str:
    stored = (name or _prefs.theme or "auto").strip().lower() or "auto"
    resolved = resolved_theme(stored)
    if stored == "auto":
        return f"auto ({resolved})"
    return stored


def palette(name: str | None = None) -> dict[str, Any]:
    return _PALETTES[resolved_theme(name)]


def rich_theme(name: str | None = None) -> Theme:
    return Theme(dict(palette(name)["styles"]))


def is_dark(name: str | None = None) -> bool:
    return bool(palette(name)["dark"])


def syntax_name(name: str | None = None) -> str:
    return str(palette(name)["syntax"])


def brand_ansi(name: str | None = None) -> str:
    return str(palette(name)["brand_ansi"])


def glyph(key: str) -> str:
    pack = FONTS.get(_prefs.font, _UNICODE)
    return pack.get(key) or _UNICODE[key]


def glyph_preview() -> str:
    keys = ("ok", "fail", "warn", "prompt", "sep", "reason")
    return " ".join(glyph(k) for k in keys)


def _normalize_theme(raw: str) -> str | None:
    token = raw.strip().lower()
    if token in THEME_NAMES:
        return token
    return None


def _normalize_font(raw: str) -> str | None:
    token = raw.strip().lower()
    if token in FONT_NAMES:
        return token
    aliases = {"plain": "ascii", "compat": "ascii", "default": "unicode", "utf8": "unicode", "utf-8": "unicode"}
    return aliases.get(token)


def set_theme(raw: str, *, persist: bool = False) -> str | None:
    name = _normalize_theme(raw)
    if name is None:
        return None
    _prefs.theme = name
    if persist:
        _save_prefs()
    return name


def set_font(raw: str, *, persist: bool = False) -> str | None:
    name = _normalize_font(raw)
    if name is None:
        return None
    _prefs.font = name
    if persist:
        _save_prefs()
    return name


def ensure_prefs() -> UiPrefs:
    global _loaded
    if _loaded:
        return _prefs
    _loaded = True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _prefs
    theme = (os.environ.get("KITE_THEME") or "").strip()
    font = (os.environ.get("KITE_FONT") or "").strip()
    if not theme or not font:
        try:
            from kite.config import UserConfig

            cfg = UserConfig.load()
            theme = theme or (cfg.theme or "")
            font = font or (cfg.font or "")
        except Exception:
            pass
    if not theme or not font:
        try:
            from kite.config import load_runtime_config

            ui = load_runtime_config()
            theme = theme or (ui.ui_theme or "")
            font = font or (ui.ui_font or "")
        except Exception:
            pass
    if _normalize_theme(theme or "auto"):
        _prefs.theme = _normalize_theme(theme or "auto") or "auto"
    if _normalize_font(font or "unicode"):
        _prefs.font = _normalize_font(font or "unicode") or "unicode"
    return _prefs


def reset_prefs(*, theme: str = "auto", font: str = "unicode") -> None:
    """Tests: pin prefs without touching disk."""
    global _loaded
    _prefs.theme = theme
    _prefs.font = font
    _loaded = True


def _save_prefs() -> None:
    from kite.config import UserConfig

    cfg = UserConfig.load()
    cfg.theme = _prefs.theme
    cfg.font = _prefs.font
    cfg.save()
