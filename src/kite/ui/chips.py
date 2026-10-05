"""Task list rendering for the live plan checklist.

The scroll-print path only needs a glanceable summary, so `render_plan_tasks`
defaults to a single line; the itemized checklist stays available behind
`compact=False` for on-demand and verbose rendering.
"""

from __future__ import annotations

from rich.text import Text

from kite.ui.state import TodoItem
from kite.ui.style import GUTTER
from kite.ui.theme import glyph

# Caps chosen so the compact line still fits an 80-col terminal next to the bar.
_ROW_MAX = 52
_ACTIVE_MAX = 40


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


def _plan_mark(todos: list[TodoItem]) -> tuple[str, str]:
    """Collapse the plan to one glyph so the header reads as a status, not a list."""
    statuses = {item.status for item in todos}
    if statuses == {"completed"}:
        return glyph("ok"), "kite.task.done"
    if "in_progress" in statuses:
        return glyph("spin"), "kite.task.active"
    return glyph("todo"), "kite.task.pending"


def _headline_item(todos: list[TodoItem]) -> str:
    """Show the task in flight, else the next one up — otherwise the line is static."""
    for wanted in ("in_progress", "pending"):
        item = next((i for i in todos if i.status == wanted), None)
        if item is not None:
            return item.content[:_ACTIVE_MAX]
    return ""


def render_task_row(item: TodoItem, *, tick: int = 0) -> Text:
    """Colourful task row with status badge."""
    if item.status == "completed":
        mark, mark_style = glyph("ok"), "kite.task.done"
        text_style = "kite.task.done"
    elif item.status == "in_progress":
        mark, mark_style = glyph("spin"), "kite.task.active"
        text_style = "kite.task.active"
    else:
        mark, mark_style = glyph("todo"), "kite.task.pending"
        text_style = "kite.task.pending"

    badge, badge_style = _status_badge(item.status)
    content = item.content[:_ROW_MAX]

    line = Text()
    line.append(f"{GUTTER}{mark} ", style=mark_style)
    line.append(content, style=text_style)
    line.append("  ", style="")
    line.append(badge, style=badge_style)
    line.append("\n")
    return line


def _render_header(todos: list[TodoItem], *, tick: int = 0) -> Text:
    done = sum(1 for item in todos if item.status == "completed")
    total = len(todos)
    mark, mark_style = _plan_mark(todos)
    active = _headline_item(todos)

    t = Text()
    t.append(f"{GUTTER}{mark} ", style=mark_style)
    t.append("Tasks", style="kite.task")
    t.append(f"  {done}/{total}", style="kite.highlight")
    t.append("  ", style="")
    t.append_text(_progress_bar(done, total))
    # Nothing in flight and nothing pending: the bar alone tells the whole story.
    if active:
        t.append(f"  {glyph('sep')} ", style="kite.muted")
        t.append(active, style="kite.task.active")
    t.append("\n")
    return t


def render_plan_tasks(
    todos: list[TodoItem], *, tick: int = 0, compact: bool = True
) -> Text:
    """Render the plan checklist. Compact prints one line; the full form lists every item."""
    if not todos:
        return Text()
    if compact:
        return _render_header(todos, tick=tick)

    t = _render_header(todos, tick=tick)
    for item in todos:
        t.append_text(render_task_row(item, tick=tick))
    return t
