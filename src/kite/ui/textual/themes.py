"""Textual CSS themes derived from kite.ui.theme palettes."""

from __future__ import annotations

from kite.ui.theme import ensure_prefs, resolved_theme, ui_colors


def textual_css(theme_name: str | None = None) -> str:
    """Build Textual design tokens from the active Kite palette."""
    ensure_prefs()
    name = resolved_theme(theme_name)
    ui = ui_colors(name)
    accent = ui.accent or "#c9a227"
    muted = ui.muted or "#6e6e6e"
    completion_bg = ui.completion_bg or "#111111"
    completion_fg = ui.completion_current_fg or "#a8ffff"
    toolbar_fg = ui.toolbar_fg or muted
    return f"""
Screen {{
    background: {completion_bg};
}}
Header, Footer {{
    background: {completion_bg};
    color: {toolbar_fg};
}}
#transcript {{
    border: solid {accent};
}}
#status-line, #flash {{
    color: {muted};
}}
#flash {{
    color: {accent};
}}
Composer {{
    border: tall {accent};
}}
CompletePopup {{
    border: solid {accent};
    background: {completion_bg};
}}
Sidebar {{
    border: solid {accent};
    background: {completion_bg};
}}
.approval-dialog {{
    border: thick {accent};
    background: {completion_bg};
}}
OptionList > .option-list--option-highlighted {{
    background: {ui.completion_current_bg or '#003333'};
    color: {completion_fg};
}}
"""


def apply_theme_to_app(app, theme_name: str | None = None) -> str:
    """Register palette CSS on a Textual app; returns resolved theme name."""
    ensure_prefs()
    name = resolved_theme(theme_name)
    app.stylesheet.clear()
    app.stylesheet.add_source(textual_css(name))
    return name
