"""Compact tool chips and task rows — beautifului.dev patterns for TTY."""

from __future__ import annotations

from rich.text import Text

from kite.ui.diff import render_diff_stat
from kite.ui.state import TodoItem
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def render_tool_chip(tool: str, detail: str = "", *, running: bool = False) -> Text:
    """Pill-style tool chip: ╭ edit · path ╮"""
    line = Text()
    line.append(f"{GUTTER}{glyph('chip_l')}", style="kite.muted")
    line.append(tool, style="kite.tool bold")
    if detail:
        line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append(detail[:80], style="kite.muted")
    if running:
        line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append(glyph("reason"), style="kite.pending")
    line.append(glyph("chip_r"), style="kite.muted")
    return line


def render_tool_chip_done(
    tool: str,
    *,
    ok: bool = True,
    meta: str = "",
    warn: bool = False,
    added: int | None = None,
    deleted: int | None = None,
) -> Text:
    if warn:
        mark, style = glyph("warn"), "kite.pending"
    elif ok:
        mark, style = glyph("ok"), "kite.success"
    else:
        mark, style = glyph("fail"), "kite.error"
    line = Text()
    line.append(f"{GUTTER}{mark} ", style=style)
    line.append(tool, style=style)
    if meta:
        line.append(f"  {meta}", style="kite.muted")
    if added is not None or deleted is not None:
        line.append("  ")
        line.append_text(render_diff_stat(added or 0, deleted or 0, bar=False))
    return line


def _status_badge(status: str) -> tuple[str, str]:
    if status == "completed":
        return "Done", "kite.success"
    if status == "in_progress":
        return "In progress", "kite.pending"
    return "Pending", "kite.muted"


def render_task_row(item: TodoItem, *, tick: int = 0) -> Text:
    """Task row with trailing status badge — beautifului task list."""
    if item.status == "completed":
        mark, mark_style = glyph("ok"), "kite.success"
    elif item.status == "in_progress":
        mark = glyph("spin") if tick % 2 == 0 else "*"
        mark_style = "kite.pending"
    else:
        mark, mark_style = glyph("todo"), "kite.muted"

    badge, badge_style = _status_badge(item.status)
    content = item.content[:56]
    pad = max(1, 40 - len(content))

    line = Text()
    line.append(f"{GUTTER}{mark} ", style=mark_style)
    line.append(content, style=mark_style if item.status != "pending" else "kite.muted")
    line.append(" " * min(pad, 12), style="")
    line.append(badge, style=badge_style)
    line.append("\n")
    return line


def render_plan_tasks(todos: list[TodoItem], *, tick: int = 0) -> Text:
    t = Text()
    if not todos:
        return t
    done = sum(1 for item in todos if item.status == "completed")
    t.append(f"tasks  ({done}/{len(todos)})\n", style="kite.plan")
    for item in todos:
        t.append_text(render_task_row(item, tick=tick))
    return t
