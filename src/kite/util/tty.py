"""TTY detection for interactive CLI paths."""

from __future__ import annotations

import os
import sys


def is_interactive_tty(*, require_stdout: bool = True) -> bool:
    """True when stdin is a TTY and (optionally) stdout is too."""
    if not sys.stdin.isatty():
        return False
    return sys.stdout.isatty() if require_stdout else True


# Markers Orca exports inside managed/relayed sessions (mobile included).
ORCA_RELAY_MARKERS = (
    "ORCA_RELAY",
    "ORCA_SESSION",
    "ORCA_SESSION_ID",
    "ORCA_CLI_COMMAND",
    "ORCA_DEV_REPO_ROOT",
    "ORCA_WORKTREE",
    "ORCA_WORKTREE_ID",
    "ORCA_WORKSPACE_ID",
    "ORCA_TERMINAL_HANDLE",
    "ORCA_PANE_KEY",
    "ORCA_TAB_ID",
)

#: Narrow rendering width assumed while relayed (matches the <60 compact tier).
RELAY_WIDTH = 60


def _env_flag(name: str) -> bool | None:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def is_orca_relay() -> bool:
    """True when running inside an Orca-managed/relayed session.

    Narrow/compact rendering gates on this — never on raw terminal width —
    so desktop defaults stay untouched. ``KITE_COMPACT_UI`` forces the
    verdict either way (1/on or 0/off).
    """
    forced = _env_flag("KITE_COMPACT_UI")
    if forced is not None:
        return forced
    return any((os.environ.get(name) or "").strip() for name in ORCA_RELAY_MARKERS)


def relay_width(default_width: int) -> int:
    """Clamp a detected console width while relayed; passthrough otherwise."""
    if is_orca_relay():
        return min(int(default_width), RELAY_WIDTH)
    return int(default_width)
