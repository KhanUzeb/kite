"""Compact tool chips and task rows — colourful, smooth task list."""

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


def _progress_bar(done: int, total: int, width: int = 16) -> Text:
    bar = Text()
    if total <= 0:
        return bar
    filled = max(0, min(width, int(width * done / total)))
    bar.append(glyph("bar_fill") * filled, style="kite.task.bar")
    bar.append(glyph("bar_empty") * (width - filled), style="kite.task.bar_empty")
    return bar


def _status_badge(status: str) -> tuple[str, str]:
    if status == "completed":
        return "Done", "kite.task.done"
    if status == "in_progress":
        return "In progress", "kite.task.active"
    return "To do", "kite.task.pending"


def render_task_row(item: TodoItem, *, tick: int = 0) -> Text:
    """Colourful task row with status badge."""
    if item.status == "completed":
        mark, mark_style = glyph("ok"), "kite.task.done"
        text_style = "kite.task.done"
    elif item.status == "in_progress":
        mark = glyph("spin") if tick % 2 == 0 else "◆"
        mark_style = "kite.task.active"
        text_style = "kite.task.active"
    else:
        mark, mark_style = glyph("todo"), "kite.task.pending"
        text_style = "kite.task.pending"

    badge, badge_style = _status_badge(item.status)
    content = item.content[:56]

    line = Text()
    line.append(f"{GUTTER}{mark} ", style=mark_style)
    line.append(content, style=text_style)
    line.append("  ", style="")
    line.append(badge, style=badge_style)
    line.append("\n")
    return line


def render_plan_tasks(todos: list[TodoItem], *, tick: int = 0) -> Text:
    t = Text()
    if not todos:
        return t
    done = sum(1 for item in todos if item.status == "completed")
    total = len(todos)
    active = next((item.content[:40] for item in todos if item.status == "in_progress"), "")

    t.append(f"{GUTTER}", style="kite.muted")
    t.append("Tasks", style="kite.task")
    t.append(f"  {done}/{total}", style="kite.highlight")
    t.append("  ", style="")
    t.append_text(_progress_bar(done, total))
    if active:
        t.append(f"  {glyph('sep')} ", style="kite.muted")
        t.append(active, style="kite.task.active")
    t.append("\n")

    for item in todos:
        t.append_text(render_task_row(item, tick=tick))
    return t
