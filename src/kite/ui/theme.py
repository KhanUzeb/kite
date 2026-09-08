"""Terminal palettes and glyph packs — /theme and /font.

A CLI cannot change the host typeface. `font` here is the glyph pack
(unicode vs ascii) so broken terminals still read cleanly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich.theme import Theme

THEME_NAMES = (
    "auto",
    "kite",
    "dark",
    "light",
    "dim",
    "mono",
    "monochrome",
    "catppuccin",
    "ember",
    "forest",
    "hues",
)

FONT_NAMES = ("unicode", "ascii")

THEME_HELP = {
    "auto": "follow the terminal (COLORFGBG)",
    "kite": "bright cyan brand on dark",
    "dark": "near-black UI, bright cyan accents",
    "light": "blue brand on light terminals",
    "dim": "low-contrast",
    "mono": "no color, bold errors only",
    "monochrome": "grayscale with subtle contrast",
    "catppuccin": "pastel mocha — lavender brand, pink accent",
    "ember": "warm charcoal — amber brand, ember glow",
    "forest": "deep green — moss brand, leaf accent",
    "hues": "vivid accents — purple brand, rainbow tools",
}

FONT_HELP = {
    "unicode": "+ ! > * — plain symbols (default)",
    "ascii": "+ ! > — strict 7-bit ASCII",
}

_THEME_ALIASES = {
    "catpuccin": "catppuccin",
    "green-forest": "forest",
    "greenforest": "forest",
    "green_forest": "forest",
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
    "kite.terminal": "#8a8a8a",
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
    "kite.flash": "bold bright_yellow",
}


def _styles(**overrides: str) -> dict[str, str]:
    out = dict(_KITE_STYLES)
    out.update(overrides)
    return out


@dataclass(frozen=True)
class PaletteUi:
    muted: str
    accent: str
    placeholder: str
    toolbar_bg: str
    toolbar_fg: str
    completion_bg: str
    completion_fg: str
    completion_current_bg: str
    completion_current_fg: str
    completion_meta: str
    completion_meta_current: str
    scrollbar_bg: str
    scrollbar_btn: str
    autosuggest: str
    prompt: str


def _dark_ui(
    *,
    muted: str = "#555555",
    accent: str = "#c9a227",
    placeholder: str = "#4a4a4a",
    toolbar_bg: str = "#050505",
    toolbar_fg: str = "#5c5c5c",
    completion_bg: str = "#050505",
    completion_fg: str = "#b8b8b8",
    completion_current_bg: str = "#003333",
    completion_current_fg: str = "#a8ffff",
    completion_meta: str = "#555555",
    completion_meta_current: str = "#7a9a9a",
    scrollbar_bg: str = "#0a0a0a",
    scrollbar_btn: str = "#2a2a2a",
    autosuggest: str = "#3a3a3a",
    prompt: str = "ansibrightcyan bold",
) -> PaletteUi:
    return PaletteUi(
        muted=muted,
        accent=accent,
        placeholder=placeholder,
        toolbar_bg=toolbar_bg,
        toolbar_fg=toolbar_fg,
        completion_bg=completion_bg,
        completion_fg=completion_fg,
        completion_current_bg=completion_current_bg,
        completion_current_fg=completion_current_fg,
        completion_meta=completion_meta,
        completion_meta_current=completion_meta_current,
        scrollbar_bg=scrollbar_bg,
        scrollbar_btn=scrollbar_btn,
        autosuggest=autosuggest,
        prompt=prompt,
    )


def _light_ui(
    *,
    muted: str = "#666666",
    accent: str = "#9a7b0a",
    placeholder: str = "#888888",
    toolbar_bg: str = "#f0f0f0",
    toolbar_fg: str = "#555555",
    completion_bg: str = "#ffffff",
    completion_fg: str = "#222222",
    completion_current_bg: str = "#d6ebff",
    completion_current_fg: str = "#000000",
    completion_meta: str = "#777777",
    completion_meta_current: str = "#444444",
    scrollbar_bg: str = "#eeeeee",
    scrollbar_btn: str = "#cccccc",
    autosuggest: str = "#aaaaaa",
    prompt: str = "ansiblue bold",
) -> PaletteUi:
    return PaletteUi(
        muted=muted,
        accent=accent,
        placeholder=placeholder,
        toolbar_bg=toolbar_bg,
        toolbar_fg=toolbar_fg,
        completion_bg=completion_bg,
        completion_fg=completion_fg,
        completion_current_bg=completion_current_bg,
        completion_current_fg=completion_current_fg,
        completion_meta=completion_meta,
        completion_meta_current=completion_meta_current,
        scrollbar_bg=scrollbar_bg,
        scrollbar_btn=scrollbar_btn,
        autosuggest=autosuggest,
        prompt=prompt,
    )


def _entry(
    *,
    styles: dict[str, str],
    dark: bool,
    syntax: str,
    brand_ansi: str,
    brand_fg: str | None = None,
    ui: PaletteUi,
) -> dict[str, Any]:
    return {
        "styles": styles,
        "dark": dark,
        "syntax": syntax,
        "brand_ansi": brand_ansi,
        "brand_fg": brand_fg or brand_ansi,
        "ui": ui,
    }


_PALETTES: dict[str, dict[str, Any]] = {
    "kite": _entry(
        styles=_styles(),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansibrightcyan",
        ui=_dark_ui(accent="#c9a227"),
    ),
    "dark": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold bright_cyan",
                "kite.muted": "#555555",
                "kite.thinking": "italic #555555",
                "kite.reasoning": "italic #555555",
                "kite.diff.meta": "#444444",
                "kite.diff.ctx": "#666666",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansibrightcyan",
        ui=_dark_ui(),
    ),
    "light": _entry(
        styles=_styles(
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
        dark=False,
        syntax="ansi_light",
        brand_ansi="ansiblue",
        ui=_light_ui(),
    ),
    "dim": _entry(
        styles=_styles(
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
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansicyan",
        ui=_dark_ui(
            accent="#8a7a4a",
            toolbar_bg="#0a0a0a",
            completion_current_bg="#1a2a2a",
            completion_current_fg="#88aaaa",
        ),
    ),
    "mono": _entry(
        styles=_styles(
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
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansiwhite",
        ui=_dark_ui(
            accent="#aaaaaa",
            prompt="bold",
            completion_current_bg="#222222",
            completion_current_fg="#ffffff",
        ),
    ),
    "monochrome": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold #d4d4d4",
                "kite.thinking": "italic #6b6b6b",
                "kite.reasoning": "italic #6b6b6b",
                "kite.success": "#b8b8b8",
                "kite.pending": "#9a9a9a",
                "kite.error": "bold #f0f0f0",
                "kite.muted": "#707070",
                "kite.tool": "#c0c0c0",
                "kite.diff.add": "#a8a8a8",
                "kite.diff.del": "#686868",
                "kite.diff.hunk": "bold #d0d0d0",
                "kite.diff.meta": "#5a5a5a",
                "kite.diff.ctx": "#787878",
                "kite.plan": "#b0b0b0",
                "kite.build": "bold #d8d8d8",
                "kite.accent": "#e0e0e0",
                "kite.highlight": "#f5f5f5",
                "kite.task": "#c8c8c8",
                "kite.task.done": "#a0a0a0",
                "kite.task.active": "bold #f0f0f0",
                "kite.task.pending": "#808080",
                "kite.pick": "#c0c0c0",
                "kite.pick.current": "bold #ffffff",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansiwhite",
        brand_fg="#e0e0e0",
        ui=_dark_ui(
            muted="#707070",
            accent="#c8c8c8",
            placeholder="#505050",
            toolbar_bg="#121212",
            toolbar_fg="#8a8a8a",
            completion_bg="#121212",
            completion_fg="#c8c8c8",
            completion_current_bg="#2a2a2a",
            completion_current_fg="#ffffff",
            prompt="#e0e0e0 bold",
        ),
    ),
    "catppuccin": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold #89b4fa",
                "kite.thinking": "italic #6c7086",
                "kite.reasoning": "italic #6c7086",
                "kite.muted": "#6c7086",
                "kite.terminal": "#7f849c",
                "kite.tool": "#89dceb",
                "kite.success": "bold #a6e3a1",
                "kite.pending": "bold #f9e2af",
                "kite.error": "bold #f38ba8",
                "kite.diff.add": "bold #a6e3a1",
                "kite.diff.del": "bold #f38ba8",
                "kite.diff.hunk": "bold #89b4fa",
                "kite.diff.meta": "#585b70",
                "kite.diff.ctx": "#7f849c",
                "kite.plan": "bold #f9e2af",
                "kite.build": "bold #a6e3a1",
                "kite.accent": "bold #f5c2e7",
                "kite.highlight": "bold #cba6f7",
                "kite.task": "bold #cba6f7",
                "kite.task.done": "#a6e3a1",
                "kite.task.active": "bold #89b4fa",
                "kite.task.pending": "#7f849c",
                "kite.task.bar": "#a6e3a1",
                "kite.task.bar_empty": "#313244",
                "kite.pick": "#89b4fa",
                "kite.pick.current": "bold #a6e3a1",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansiblue",
        brand_fg="#89b4fa",
        ui=_dark_ui(
            muted="#6c7086",
            accent="#f5c2e7",
            placeholder="#45475a",
            toolbar_bg="#11111b",
            toolbar_fg="#a6adc8",
            completion_bg="#11111b",
            completion_fg="#cdd6f4",
            completion_current_bg="#313244",
            completion_current_fg="#89b4fa",
            completion_meta="#6c7086",
            completion_meta_current="#b4befe",
            scrollbar_bg="#181825",
            scrollbar_btn="#313244",
            autosuggest="#45475a",
            prompt="#89b4fa bold",
        ),
    ),
    "ember": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold #ff9f43",
                "kite.thinking": "italic #8a7a6a",
                "kite.reasoning": "italic #8a7a6a",
                "kite.muted": "#8a7a6a",
                "kite.terminal": "#a09080",
                "kite.tool": "#ffb347",
                "kite.success": "bold #7cb342",
                "kite.pending": "bold #ffd54f",
                "kite.error": "bold #ff6b6b",
                "kite.diff.add": "bold #8bc34a",
                "kite.diff.del": "bold #ef5350",
                "kite.diff.hunk": "bold #ff9f43",
                "kite.diff.meta": "#6a5a4a",
                "kite.diff.ctx": "#9a8a7a",
                "kite.plan": "bold #ffd54f",
                "kite.build": "bold #8bc34a",
                "kite.accent": "bold #ff7043",
                "kite.highlight": "bold #ffab40",
                "kite.task": "bold #ff8a65",
                "kite.task.done": "#8bc34a",
                "kite.task.active": "bold #ff9f43",
                "kite.task.pending": "#a08060",
                "kite.task.bar": "#8bc34a",
                "kite.task.bar_empty": "#2a2018",
                "kite.pick": "#ff9f43",
                "kite.pick.current": "bold #8bc34a",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansiyellow",
        brand_fg="#ff9f43",
        ui=_dark_ui(
            muted="#8a7a6a",
            accent="#ff7043",
            placeholder="#4a3a2a",
            toolbar_bg="#1a1208",
            toolbar_fg="#c8b8a8",
            completion_bg="#1a1208",
            completion_fg="#f0e0d0",
            completion_current_bg="#3a2818",
            completion_current_fg="#ffab40",
            completion_meta="#8a7a6a",
            completion_meta_current="#ffb347",
            scrollbar_bg="#221810",
            scrollbar_btn="#3a2818",
            autosuggest="#4a3a2a",
            prompt="#ff9f43 bold",
        ),
    ),
    "forest": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold #4ade80",
                "kite.thinking": "italic #5a7a5a",
                "kite.reasoning": "italic #5a7a5a",
                "kite.muted": "#5a7a5a",
                "kite.terminal": "#6a8a6a",
                "kite.tool": "#86efac",
                "kite.success": "bold #22c55e",
                "kite.pending": "bold #a3e635",
                "kite.error": "bold #f87171",
                "kite.diff.add": "bold #4ade80",
                "kite.diff.del": "bold #ef4444",
                "kite.diff.hunk": "bold #34d399",
                "kite.diff.meta": "#3a5a3a",
                "kite.diff.ctx": "#6a8a6a",
                "kite.plan": "bold #a3e635",
                "kite.build": "bold #22c55e",
                "kite.accent": "bold #6ee7b7",
                "kite.highlight": "bold #86efac",
                "kite.task": "bold #6ee7b7",
                "kite.task.done": "#22c55e",
                "kite.task.active": "bold #4ade80",
                "kite.task.pending": "#4a6a4a",
                "kite.task.bar": "#22c55e",
                "kite.task.bar_empty": "#142818",
                "kite.pick": "#4ade80",
                "kite.pick.current": "bold #22c55e",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansigreen",
        brand_fg="#4ade80",
        ui=_dark_ui(
            muted="#5a7a5a",
            accent="#6ee7b7",
            placeholder="#2a4a2a",
            toolbar_bg="#0a1810",
            toolbar_fg="#8ab88a",
            completion_bg="#0a1810",
            completion_fg="#d0f0d0",
            completion_current_bg="#1a3828",
            completion_current_fg="#86efac",
            completion_meta="#5a7a5a",
            completion_meta_current="#6ee7b7",
            scrollbar_bg="#102018",
            scrollbar_btn="#1a3828",
            autosuggest="#2a4a2a",
            prompt="#4ade80 bold",
        ),
    ),
    "hues": _entry(
        styles=_styles(
            **{
                "kite.brand": "bold #a78bfa",
                "kite.thinking": "italic #7a7a9a",
                "kite.reasoning": "italic #7a7a9a",
                "kite.muted": "#7a7a9a",
                "kite.terminal": "#9090b0",
                "kite.tool": "#38bdf8",
                "kite.success": "bold #4ade80",
                "kite.pending": "bold #fbbf24",
                "kite.error": "bold #f472b6",
                "kite.diff.add": "bold #4ade80",
                "kite.diff.del": "bold #f472b6",
                "kite.diff.hunk": "bold #38bdf8",
                "kite.diff.meta": "#5a5a7a",
                "kite.diff.ctx": "#8a8aaa",
                "kite.plan": "bold #fbbf24",
                "kite.build": "bold #34d399",
                "kite.accent": "bold #f472b6",
                "kite.highlight": "bold #38bdf8",
                "kite.task": "bold #c084fc",
                "kite.task.done": "#4ade80",
                "kite.task.active": "bold #38bdf8",
                "kite.task.pending": "#7c8aff",
                "kite.task.bar": "#4ade80",
                "kite.task.bar_empty": "#1a1a2e",
                "kite.pick": "#a78bfa",
                "kite.pick.current": "bold #4ade80",
            }
        ),
        dark=True,
        syntax="ansi_dark",
        brand_ansi="ansimagenta",
        brand_fg="#a78bfa",
        ui=_dark_ui(
            muted="#7a7a9a",
            accent="#f472b6",
            placeholder="#3a3a5a",
            toolbar_bg="#12121f",
            toolbar_fg="#b0b0d0",
            completion_bg="#12121f",
            completion_fg="#e8e8ff",
            completion_current_bg="#2a2048",
            completion_current_fg="#c4b5fd",
            completion_meta="#7a7a9a",
            completion_meta_current="#f0abfc",
            scrollbar_bg="#1a1a2e",
            scrollbar_btn="#2a2048",
            autosuggest="#3a3a5a",
            prompt="#a78bfa bold",
        ),
    ),
}

_UNICODE = {
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
    "checkpoint": "*",
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
    "checkpoint": "*",
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


def _canonical_theme(raw: str) -> str:
    token = raw.strip().lower()
    return _THEME_ALIASES.get(token, token)


def resolved_theme(name: str | None = None) -> str:
    raw = _canonical_theme(name or _prefs.theme or "auto")
    if raw == "auto":
        return "light" if terminal_is_light() else "kite"
    if raw in _PALETTES:
        return raw
    return "kite"


def theme_label(name: str | None = None) -> str:
    stored = _canonical_theme(name or _prefs.theme or "auto") or "auto"
    resolved = resolved_theme(stored)
    if stored == "auto":
        return f"auto ({resolved})"
    return stored


def palette(name: str | None = None) -> dict[str, Any]:
    return _PALETTES[resolved_theme(name)]


def ui_colors(name: str | None = None) -> PaletteUi:
    return palette(name)["ui"]


def rich_theme(name: str | None = None) -> Theme:
    return Theme(dict(palette(name)["styles"]))


def is_dark(name: str | None = None) -> bool:
    return bool(palette(name)["dark"])


def syntax_name(name: str | None = None) -> str:
    return str(palette(name)["syntax"])


def brand_ansi(name: str | None = None) -> str:
    return str(palette(name)["brand_ansi"])


def brand_fg(name: str | None = None) -> str:
    return str(palette(name)["brand_fg"])


def pt_style_dict(name: str | None = None) -> dict[str, str]:
    ui = ui_colors(name)
    return {
        "prompt": ui.prompt,
        "placeholder": ui.placeholder,
        "bottom-toolbar": f"noreverse {ui.toolbar_fg} bg:{ui.toolbar_bg}",
        "completion-menu": f"bg:{ui.completion_bg} {ui.completion_fg}",
        "completion-menu.completion": f"bg:{ui.completion_bg} {ui.completion_fg}",
        "completion-menu.completion.current": (
            f"bg:{ui.completion_current_bg} {ui.completion_current_fg} bold"
        ),
        "completion-menu.meta.completion": ui.completion_meta,
        "completion-menu.meta.completion.current": ui.completion_meta_current,
        "completion-menu.multi-column-meta": f"bg:{ui.scrollbar_bg} {ui.completion_meta}",
        "scrollbar.background": f"bg:{ui.scrollbar_bg}",
        "scrollbar.button": f"bg:{ui.scrollbar_btn}",
        "auto-suggestion": ui.autosuggest,
    }


def glyph(key: str) -> str:
    pack = FONTS.get(_prefs.font, _UNICODE)
    return pack.get(key) or _UNICODE[key]


def glyph_preview() -> str:
    keys = ("ok", "fail", "warn", "prompt", "sep", "reason")
    return " ".join(glyph(k) for k in keys)


def _normalize_theme(raw: str) -> str | None:
    token = _canonical_theme(raw)
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


def _pref_from_env(key: str) -> str:
    return (os.environ.get(key) or "").strip()


def _pref_from_user_config() -> tuple[str, str]:
    try:
        from kite.config import UserConfig

        cfg = UserConfig.load()
        return (cfg.theme or "", cfg.font or "")
    except Exception:
        return ("", "")


def _pref_from_runtime_config() -> tuple[str, str]:
    try:
        from kite.config import load_runtime_config

        ui = load_runtime_config()
        return (ui.ui_theme or "", ui.ui_font or "")
    except Exception:
        return ("", "")


def _apply_pref(value: str, normalizer: Any, attr: str) -> None:
    resolved = normalizer(value)
    if resolved:
        setattr(_prefs, attr, resolved)


def ensure_prefs() -> UiPrefs:
    global _loaded
    if _loaded:
        return _prefs
    _loaded = True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _prefs

    theme = _pref_from_env("KITE_THEME")
    font = _pref_from_env("KITE_FONT")
    if not theme or not font:
        cfg_theme, cfg_font = _pref_from_user_config()
        theme = theme or cfg_theme
        font = font or cfg_font
    if not theme or not font:
        rt_theme, rt_font = _pref_from_runtime_config()
        theme = theme or rt_theme
        font = font or rt_font

    _apply_pref(theme or "auto", _normalize_theme, "theme")
    _apply_pref(font or "unicode", _normalize_font, "font")
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
