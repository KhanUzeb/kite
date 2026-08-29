"""Kite CLI style guide — one palette, symbols never color-only.

Palette
-------
  brand     cyan      product chrome (name, prompt)
  assistant magenta   model speech
  success   green     applied / done / allow
  pending   yellow    approval wait / in-progress
  error     red       blocked / fail / interrupt
  muted     dim       collapsed output, secondary meta
  user      white     human input

Symbols (always paired with color)
----------------------------------
  ✓  success/applied     ✗  error/denied
  ⚠  approval needed     ●  in-progress
  ○  pending todo        ▸  collapsed tool
  ▾  expanded tool       ❯  input prompt
  ↻  compact/retry       ·  status separator

Spacing
-------
  gutter        2 spaces before body text
  tool indent   2 spaces
  diff indent   4 spaces (unified hunk body)
  collapse      first 4 lines, then dim "+N lines  /expand"
  panels        padding=(0, 1), no extra blank lines between
                consecutive tool rows
  footer        one line, never wraps if terminal ≥ 80 cols
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.theme import Theme

KITE_THEME = Theme(
    {
        "kite.brand": "bold cyan",
        "kite.assistant": "bold magenta",
        "kite.user": "bold white",
        "kite.success": "green",
        "kite.pending": "yellow",
        "kite.error": "bold red",
        "kite.muted": "dim",
        "kite.tool": "bold cyan",
        "kite.diff.add": "green",
        "kite.diff.del": "red",
        "kite.diff.hunk": "cyan",
        "kite.diff.meta": "dim",
        "kite.plan": "bold yellow",
        "kite.build": "bold green",
    }
)

SYMBOL_OK = "✓"
SYMBOL_FAIL = "✗"
SYMBOL_WARN = "⚠"
SYMBOL_SPIN = "●"
SYMBOL_TODO = "○"
SYMBOL_COLLAPSE = "▸"
SYMBOL_EXPAND = "▾"
SYMBOL_PROMPT = "❯"
SYMBOL_COMPACT = "↻"
SYMBOL_SEP = "·"

COLLAPSE_LINES = 4
DIFF_PREVIEW_LINES = 40
GUTTER = "  "


@dataclass(frozen=True)
class ModeChrome:
    name: str
    style: str
    label: str


PLAN = ModeChrome(name="plan", style="kite.plan", label="plan")
BUILD = ModeChrome(name="build", style="kite.build", label="build")


def make_console(*, stderr: bool = False, quiet: bool = False) -> Console:
    return Console(
        stderr=stderr,
        quiet=quiet,
        theme=KITE_THEME,
        highlight=False,
        soft_wrap=False,
    )


def syntax_theme(console: Console) -> str:
    """Respect the terminal: light backgrounds get ansi_light."""
    if console.color_system is None:
        return "ansi_dark"
    # Rich cannot reliably know bg; prefer env, else dark (most terminals).
    import os

    colorfgbg = os.environ.get("COLORFGBG", "")
    if ";" in colorfgbg:
        try:
            bg = int(colorfgbg.split(";")[-1])
            if bg >= 8:  # light-ish xterm bg index
                return "ansi_light"
        except ValueError:
            pass
    return "ansi_dark"
