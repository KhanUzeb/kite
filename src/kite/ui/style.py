"""Kite CLI style — Codex cells + Antigravity effort language.

Visual language (stolen, not invented)
--------------------------------------
  Codex CLI
    ›  user turn (dim bullet, no box)
    …  thinking (italic dim; a cell, not mixed into the answer)
    •  answer  (normal weight; separate cell)
    status words: thinking / working
    footer: one line, · separators, approval lives here
    no decorative panels around you / result / speech

  Antigravity CLI
    effort badge on the footer (fast | thinking)
    compaction as a boundary marker, not a banner
    tools as one-line rows
    keyboard-first, no flicker, no chrome

Palette
--------
  brand     cyan      product name, composer
  thinking  italic dim  internal chain-of-thought
  answer    default   final model reply
  success   green     applied / done / allow
  pending   yellow    approval wait / in-progress / effort
  error     red       blocked / fail / interrupt
  muted     dim       collapsed output, secondary meta
  user      default   human input

Symbols (always paired with color — never color alone)
-------------------------------------------------------
  ✓  success/applied     ✗  error/denied
  ⚠  approval needed     ●  in-progress
  ○  pending todo        ▸  tool row
  ▾  expanded            ›  user / composer
  •  answer cell         …  thinking cell
  ↻  compact boundary    ·  status separator

Spacing
-------
  gutter        2 spaces before body text
  cell indent   subsequent lines of a cell align under the glyph
  collapse      first 4 lines, then dim "+N lines  /expand"
  footer        one line, never wraps if terminal ≥ 80 cols
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.theme import Theme

KITE_THEME = Theme(
    {
        "kite.brand": "cyan",
        "kite.thinking": "italic dim",
        "kite.reasoning": "italic dim",  # alias — UI language is "thinking"
        "kite.answer": "default",
        "kite.assistant": "default",
        "kite.user": "default",
        "kite.success": "green",
        "kite.pending": "yellow",
        "kite.error": "bold red",
        "kite.muted": "dim",
        "kite.tool": "cyan",
        "kite.diff.add": "green",
        "kite.diff.del": "red",
        "kite.diff.hunk": "cyan",
        "kite.diff.meta": "dim",
        "kite.plan": "yellow",
        "kite.build": "green",
    }
)

SYMBOL_OK = "✓"
SYMBOL_FAIL = "✗"
SYMBOL_WARN = "⚠"
SYMBOL_SPIN = "●"
SYMBOL_TODO = "○"
SYMBOL_COLLAPSE = "▸"
SYMBOL_EXPAND = "▾"
SYMBOL_PROMPT = "›"
SYMBOL_USER = "›"
SYMBOL_AGENT = "•"
SYMBOL_COMPACT = "↻"
SYMBOL_SEP = "·"
SYMBOL_REASON = "…"

CHANNEL_PREFIX = {
    "thinking": SYMBOL_REASON + " ",
    "answer": SYMBOL_AGENT + " ",
}

COLLAPSE_LINES = 4
DIFF_PREVIEW_LINES = 40
PREVIEW_FILE_MAX_BYTES = 64_000
PREVIEW_CHUNK_BYTES = 65_536
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
