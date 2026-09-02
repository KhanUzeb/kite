"""Quiet tables — structural lines only, no decorative chrome."""

from __future__ import annotations

from rich import box
from rich.table import Table


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
