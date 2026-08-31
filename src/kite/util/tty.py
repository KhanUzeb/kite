"""TTY detection for interactive CLI paths."""

from __future__ import annotations

import sys


def is_interactive_tty(*, require_stdout: bool = True) -> bool:
    """True when stdin is a TTY and (optionally) stdout is too."""
    if not sys.stdin.isatty():
        return False
    return sys.stdout.isatty() if require_stdout else True
