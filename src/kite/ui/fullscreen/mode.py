"""Compact vs fullscreen display mode and terminal size gates."""

from __future__ import annotations

from typing import Literal

UiDisplayMode = Literal["compact", "fullscreen"]

REDUCED_FULLSCREEN_COLS = 100
REDUCED_FULLSCREEN_ROWS = 30
FULL_FULLSCREEN_COLS = 120
FULL_FULLSCREEN_ROWS = 40


def fullscreen_layout_tier(cols: int, rows: int) -> Literal["none", "reduced", "full"]:
    if cols < REDUCED_FULLSCREEN_COLS or rows < REDUCED_FULLSCREEN_ROWS:
        return "none"
    if cols < FULL_FULLSCREEN_COLS or rows < FULL_FULLSCREEN_ROWS:
        return "reduced"
    return "full"


def can_show_fullscreen(cols: int, rows: int) -> bool:
    return fullscreen_layout_tier(cols, rows) != "none"


def preferred_display_mode(
    *,
    preference: UiDisplayMode,
    cols: int,
    rows: int,
) -> UiDisplayMode:
    if preference == "fullscreen" and can_show_fullscreen(cols, rows):
        return "fullscreen"
    return "compact"
