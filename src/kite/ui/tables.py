"""Quiet tables — structural lines only, no decorative chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich import box
from rich.table import Table

if TYPE_CHECKING:
    from kite.memory.session import SessionMeta


def kite_table(title: str = "") -> Table:
    return Table(
        title=title or None,
        box=box.SIMPLE,
        pad_edge=False,
        show_edge=False,
        padding=(0, 1),
        header_style="kite.brand",
        title_style="kite.brand",
        border_style="kite.muted",
        show_lines=False,
        expand=False,
        collapse_padding=True,
        row_styles=["", "kite.muted"],
    )


def render_sessions_table(
    console: Any,
    rows: list[SessionMeta],
    *,
    title: str,
    current: str | None = None,
) -> None:
    """Sessions picker (canonical home; memory.session_format re-exports).

    One session per visually separated card: the prompt is the primary
    line, metadata (project · age · size · status · model) renders dimmed
    beneath it. The current session reads ``> … *``; long prompts
    truncate to the console width so rows stay aligned; lists taller than
    the terminal scroll via the numbered picker. Empty lists print a
    muted hint instead of an empty table.
    """
    from kite.memory.session_format import format_session_card

    if not rows:
        console.print("[dim]no sessions yet  ·  start chatting and they appear here[/]")
        return
    width = max(40, int(getattr(console, "width", 100) or 100))
    if title:
        console.print(f"[bold]{title}[/]")
        console.print()
    for meta in rows:
        prompt_line, meta_line = format_session_card(meta, current=current, width=width)
        is_current = bool(current and meta.id == current)
        prompt_style = "bold reverse" if is_current else "bold"
        # markup=False: session titles are user text — a "[bug]" prompt must
        # not parse as Rich markup (or raise MarkupError) on the way out.
        console.print(prompt_line, style=prompt_style, markup=False, highlight=False)
        console.print(meta_line, style="dim", markup=False, highlight=False)
        console.print()
    if rows:
        console.print(
            "[dim]resume:[/] [bold]kite resume <id>[/]  "
            "[dim]· filter:[/] kite sessions -q text  "
            f"[dim]· show:[/] kite sessions --show {rows[0].id}"
        )
