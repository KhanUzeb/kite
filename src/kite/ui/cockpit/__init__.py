"""Run-centric cockpit — event stream → view model → layout."""

from kite.ui.cockpit.mode import UiDisplayMode, can_show_cockpit, cockpit_layout_tier, preferred_display_mode
from kite.ui.cockpit.reducer import RunCockpitReducer
from kite.ui.cockpit.render import render_cockpit, render_cockpit_text
from kite.ui.cockpit.view_model import RunViewModel

__all__ = [
    "RunCockpitReducer",
    "RunViewModel",
    "UiDisplayMode",
    "can_show_cockpit",
    "cockpit_layout_tier",
    "preferred_display_mode",
    "render_cockpit",
    "render_cockpit_text",
]
