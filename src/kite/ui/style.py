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
  collapse      first 5 lines, then dim "+N lines  /expand"
  footer        one line, never wraps if terminal ≥ 80 cols
"""

from __future__ import annotations

import re

from rich.cells import cell_len, chop_cells
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

# Scroll-print budget per tool body. A turn that edits a big file used to paint
# 16 preview lines at start and 40 diff rows at end; /last re-prints the last
# tool call in full and /expand widens later ones, so the scrollback only needs
# enough to recognise what happened.
PREVIEW_LINES = 5
COLLAPSE_LINES = PREVIEW_LINES
# Approval previews are a deliberate pause, not scrollback: keep the wider
# window there so the user can judge the patch before answering.
DIFF_PREVIEW_LINES = 40
PREVIEW_FILE_MAX_BYTES = 64_000
PREVIEW_CHUNK_BYTES = 65_536
GUTTER = "  "
PANEL_BAR = "┊ "


def clip_text(text: str, limit: int) -> str:
    """Cut prose to display columns with an explicit ellipsis."""
    if cell_len(text) <= limit:
        return text
    if limit < 2:
        return "…"
    out = ""
    for ch in text:
        if cell_len(out + ch) > limit - 1:
            break
        out += ch
    return (out.rstrip() + "…") if out else "…"


def cell_continuation_indent(first_line_prefix: str) -> str:
    """Spaces so wrapped cell lines align under the first line body."""
    return " " * cell_len(first_line_prefix or "")


# Columns from the row edge within which a streamed word is held back rather than
# printed. Comfortably wider than a normal word, so an in-flight token still lands
# on this row; only text that is genuinely near the edge waits for the rest of
# its word.
DEFER_MARGIN = 16


def wrap_hanging_parts(
    text: str,
    *,
    first_indent: str,
    cont_indent: str,
    width: int,
    defer_tail: bool = False,
) -> tuple[str, str]:
    """Wrap one logical line; return ``(emitted, pending)``.

    Streaming cells are written with ``end=""`` to a ``soft_wrap`` console: Rich
    hands the raw line to the terminal, which wraps it at column 0 with no
    gutter. Breaking the line here instead keeps every continuation aligned
    under the cell body.

    ``first_indent`` carries the columns already occupied on the row (the
    gutter plus anything printed earlier in this same line), so a paragraph
    arriving in many small chunks wraps on the same boundaries a single chunk
    would.

    ``defer_tail`` may hold a partial word near the right edge. The caller
    prepends it to the next fragment, or flushes it when the stream closes.
    """
    if width <= 0:
        return text, ""
    occupied = cell_len(first_indent)
    if "\t" in text:
        text = (" " * occupied + text).expandtabs(8)[occupied:]
    room = max(0, width - occupied)
    cont_room = max(1, width - cell_len(cont_indent))
    if cell_len(text) <= room:
        if defer_tail and text and not text.endswith(" "):
            cut = text.rfind(" ") + 1
            # Measure from this word's start, not the chunk's start: earlier
            # words in the same chunk may have consumed the safe margin.
            if room - cell_len(text[:cut]) < DEFER_MARGIN and cell_len(text[cut:]) < cont_room:
                return text[:cut], text[cut:]
        return text, ""

    out: list[str] = []
    for match in re.finditer(r" +|[^ ]+", text):
        token = match.group()
        size = cell_len(token)
        if (
            defer_tail and match.end() == len(text) and not token.isspace()
            and room < DEFER_MARGIN and size < cont_room
        ):
            return "".join(out), token
        if size <= room:
            out.append(token)
            room -= size
            continue
        if token.isspace():
            # Preserve separators at chunk boundaries, but discard whitespace
            # that would extend beyond the right edge of a wrapped row.
            out.append(token[:room])
            room = 0
            continue
        if room < cont_room:
            out.append("\n" + cont_indent)
            room = cont_room
        if size <= room:
            out.append(token)
            room -= size
        else:
            rows = chop_cells(token, cont_room)
            out.append(("\n" + cont_indent).join(rows))
            room = cont_room - cell_len(rows[-1])
    return "".join(out), ""


def wrap_hanging(text: str, *, first_indent: str, cont_indent: str, width: int) -> str:
    """Word-wrap one complete line so continuations keep ``cont_indent``."""
    emitted, pending = wrap_hanging_parts(
        text,
        first_indent=first_indent,
        cont_indent=cont_indent,
        width=width,
    )
    return emitted + pending


def last_line_width(text: str) -> int:
    """Columns used by the final row of ``text`` — where the cursor lands."""

    tail = text.rsplit("\n", 1)[-1]
    return cell_len(tail) if tail else 0


def make_console(*, stderr: bool = False, quiet: bool = False) -> Console:
    from kite.ui.theme import ensure_prefs
    from kite.util.tty import RELAY_WIDTH, is_orca_relay

    ensure_prefs()
    width: int | None = None
    if is_orca_relay():
        # Relay-only narrow shift: render as if on a small screen. Piped
        # (non-tty) output keeps natural width so --json/logs never reflow.
        import sys as _sys

        stream = _sys.stderr if stderr else _sys.stdout
        try:
            if stream.isatty():
                width = RELAY_WIDTH
        except Exception:
            width = None
    return Console(
        stderr=stderr,
        quiet=quiet,
        theme=rich_theme(),
        highlight=False,
        soft_wrap=True,
        width=width,
    )


def syntax_theme(console: Console) -> str:
    if console.color_system is None:
        return "ansi_dark"
    return syntax_name()
