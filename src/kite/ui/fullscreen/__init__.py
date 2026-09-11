"""Optional fullscreen TUI — fluid stream projection of the same events."""

from kite.ui.fullscreen.mode import (
    UiDisplayMode,
    can_show_fullscreen,
    preferred_display_mode,
)
from kite.ui.fullscreen.reducer import FullscreenReducer
from kite.ui.fullscreen.render import render_fullscreen

__all__ = [
    "FullscreenReducer",
    "UiDisplayMode",
    "can_show_fullscreen",
    "preferred_display_mode",
    "render_fullscreen",
]
