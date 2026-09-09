"""Shared empty-state lines for REPL and CLI."""

from __future__ import annotations

from rich.text import Text

from kite.ui.style import GUTTER, SYMBOL_TODO
from kite.ui.theme import glyph


def render_empty(message: str, *, hint: str = "") -> Text:
    """Muted empty state with optional brand-colored hint."""
    line = Text()
    line.append(f"{GUTTER}{SYMBOL_TODO} ", style="kite.muted")
    line.append(message.strip(), style="kite.muted")
    if hint:
        line.append(f"  {glyph('sep')} ", style="kite.muted")
        line.append(hint.strip(), style="kite.brand")
    line.append("\n")
    return line
