"""Compact tool chips and task rows — beautifului.dev patterns for TTY."""

from __future__ import annotations

from rich.text import Text

from kite.ui.state import TodoItem
from kite.ui.style import GUTTER, SYMBOL_FAIL, SYMBOL_OK, SYMBOL_SPIN, SYMBOL_TODO


def render_tool_chip(tool: str, detail: str = "", *, running: bool = False) -> Text:
    """Pill-style tool chip: ╭ edit · path ╮"""
    line = Text()
    line.append(f"{GUTTER}╭ ", style="kite.muted")
    line.append(tool, style="kite.tool bold")
    if detail:
        line.append(" · ", style="kite.muted")
        line.append(detail[:80], style="kite.muted")
    if running:
        line.append(" · ", style="kite.muted")
        line.append("…", style="kite.pending")
    line.append(" ╮", style="kite.muted")
    return line


def render_tool_chip_done(tool: str, *, ok: bool = True, meta: str = "", warn: bool = False) -> Text:
    if warn:
        mark, style = "⚠", "kite.pending"
    elif ok:
        mark, style = SYMBOL_OK, "kite.success"
    else:
        mark, style = SYMBOL_FAIL, "kite.error"
    line = Text()
    line.append(f"{GUTTER}{mark} ", style=style)
    line.append(tool, style=style)
    if meta:
        line.append(f"  {meta}", style="kite.muted")
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
        mark, mark_style = SYMBOL_OK, "kite.success"
    elif item.status == "in_progress":
        # Alternate ●/◉ for subtle pulse on running rows
        mark = SYMBOL_SPIN if tick % 2 == 0 else "◉"
        mark_style = "kite.pending"
    else:
        mark, mark_style = SYMBOL_TODO, "kite.muted"

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
