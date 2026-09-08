"""Kite CLI style — Codex cells + Antigravity effort language.

Visual language (stolen, not invented)
--------------------------------------
  Codex CLI
    >  user turn (dim bullet, no box)
    ...  thinking (italic dim; a cell, not mixed into the answer)
    .  answer  (normal weight; separate cell)
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
  +  success/applied     x  error/denied
  !  approval needed     *  in-progress
  o  pending todo        >  tool row
  v  expanded            >  user / composer
  .  answer cell         ...  thinking cell
  ~  compact boundary    |  status separator

Spacing
-------
  gutter        2 spaces before body text
  cell indent   subsequent lines of a cell align under the glyph
  collapse      first 4 lines, then dim "+N lines  /expand"
  footer        one line, never wraps if terminal ≥ 80 cols
"""

from __future__ import annotations

from rich.console import Console

from kite.ui.theme import glyph, rich_theme, syntax_name


class _Glyph:
    """Reads the active /font pack so f-strings stay live after /font."""

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    def __str__(self) -> str:
        return glyph(self._key)

    def __repr__(self) -> str:
        return str(self)

    def __add__(self, other: object) -> str:
        return str(self) + str(other)

    def __radd__(self, other: object) -> str:
        return str(other) + str(self)

    def __eq__(self, other: object) -> bool:
        return str(self) == other

    def __hash__(self) -> int:
        return hash(self._key)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


class _ChannelPrefix:
    def get(self, channel: str, default: str = "  ") -> str:
        if channel == "thinking":
            return f"{glyph('reason')} "
        if channel == "answer":
            return f"{glyph('agent')} "
        return default


KITE_THEME = rich_theme("kite")

SYMBOL_OK = _Glyph("ok")
SYMBOL_FAIL = _Glyph("fail")
SYMBOL_WARN = _Glyph("warn")
SYMBOL_SPIN = _Glyph("spin")
SYMBOL_TODO = _Glyph("todo")
SYMBOL_COLLAPSE = _Glyph("collapse")
SYMBOL_EXPAND = _Glyph("expand")
SYMBOL_PROMPT = _Glyph("prompt")
SYMBOL_USER = _Glyph("user")
SYMBOL_AGENT = _Glyph("agent")
SYMBOL_COMPACT = _Glyph("compact")
SYMBOL_SEP = _Glyph("sep")
SYMBOL_REASON = _Glyph("reason")

CHANNEL_PREFIX = _ChannelPrefix()

COLLAPSE_LINES = 4
DIFF_PREVIEW_LINES = 40
PREVIEW_FILE_MAX_BYTES = 64_000
PREVIEW_CHUNK_BYTES = 65_536
GUTTER = "  "
PANEL_BAR = "| "


def make_console(*, stderr: bool = False, quiet: bool = False) -> Console:
    from kite.ui.theme import ensure_prefs

    ensure_prefs()
    return Console(
        stderr=stderr,
        quiet=quiet,
        theme=rich_theme(),
        highlight=False,
        soft_wrap=False,
    )


def syntax_theme(console: Console) -> str:
    if console.color_system is None:
        return "ansi_dark"
    return syntax_name()
