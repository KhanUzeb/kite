"""Fullscreen TUI is opt-in and not part of the default install."""

from __future__ import annotations

import os
import sys


def should_use_textual_tui() -> bool:
    if os.environ.get("KITE_LEGACY_TUI", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("KITE_TUI", "").strip().lower() not in {"1", "true", "yes"}:
        return False
    if not sys.stdin.isatty():
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True
