"""Quiet tables — structural lines only, no decorative chrome."""

from __future__ import annotations

from pathlib import Path
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
    """Sessions picker table (canonical home; memory.session_format re-exports)."""
    from kite.memory.session_format import (
        format_session_when,
        session_short_id,
        session_status,
        session_title,
    )

    table = Table(title=title, show_lines=False, pad_edge=False)
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Title", overflow="ellipsis", max_width=36)
    table.add_column("Model", style="cyan", no_wrap=True, max_width=22)
    table.add_column("Status", no_wrap=True)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Dir", style="dim", no_wrap=True, max_width=14)

    for meta in rows:
        date_s, time_s, rel = format_session_when(meta.updated_at)
        mark = " *" if current and meta.id == current else ""
        status = session_status(meta)
        status_style = "green" if status == "Submitted" else ("yellow" if status == "open" else "dim")
        cwd = Path(meta.cwd).name if meta.cwd else "—"
        table.add_row(
            date_s,
            time_s,
            session_title(meta, max_len=34) + mark,
            f"{meta.provider}/{meta.model}".strip("/") or "—",
            f"[{status_style}]{status}[/]",
            session_short_id(meta.id),
            cwd,
        )
    console.print(table)
    if rows:
        console.print(
            f"[dim]resume:[/] [bold]kite resume <id>[/]  "
            f"[dim]· filter:[/] kite sessions -q text  "
            f"[dim]· show:[/] kite sessions --show {rows[0].id}"
        )
