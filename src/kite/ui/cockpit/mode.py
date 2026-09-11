"""Compact vs cockpit display mode and terminal size gates."""

from __future__ import annotations

from typing import Literal

UiDisplayMode = Literal["compact", "cockpit"]

# Minimum terminal sizes (plan §10).
COMPACT_ONLY_COLS = 80
COMPACT_ONLY_ROWS = 24
REDUCED_COCKPIT_COLS = 100
REDUCED_COCKPIT_ROWS = 30
FULL_COCKPIT_COLS = 120
FULL_COCKPIT_ROWS = 40


def cockpit_layout_tier(cols: int, rows: int) -> Literal["none", "reduced", "full"]:
    """Return cockpit layout tier for the given terminal size."""
    if cols < REDUCED_COCKPIT_COLS or rows < REDUCED_COCKPIT_ROWS:
        return "none"
    if cols < FULL_COCKPIT_COLS or rows < FULL_COCKPIT_ROWS:
        return "reduced"
    return "full"


def can_show_cockpit(cols: int, rows: int) -> bool:
    return cockpit_layout_tier(cols, rows) != "none"


def preferred_display_mode(
    *,
    preference: UiDisplayMode,
    cols: int,
    rows: int,
) -> UiDisplayMode:
    """Resolve user preference against terminal constraints."""
    if preference == "cockpit" and can_show_cockpit(cols, rows):
        return "cockpit"
    return "compact"
