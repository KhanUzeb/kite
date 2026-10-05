"""Task list rendering for the live plan checklist.

The scroll-print path only needs a glanceable summary, so `render_plan_tasks`
defaults to a single line; the itemized checklist stays available behind
`compact=False` for on-demand and verbose rendering.

The line is built against the live terminal width: the count and the in-flight
item are what the reader scans for, so they stay and the progress bar is what
goes when the row runs out of columns.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from kite.ui.state import TodoItem
from kite.ui.style import GUTTER
from kite.ui.theme import glyph

# Caps chosen so the compact line still fits an 80-col terminal next to the bar.
_ROW_MAX = 52
_ACTIVE_MAX = 40
_BAR_COLUMNS = 16
# Before a trailing inline item the separator takes the wider house form, same
# as empty.py and tool_cards.py: two spaces before, one after.
def _item_sep() -> str:
    """Wider house separator before the trailing item, live for /font."""
    return f"  {glyph('sep')} "
# Below this the clipped item stops saying anything useful, so the bar goes
# before the item is squeezed down to a stub.
_MIN_ITEM_COLUMNS = 28


def _clip(text: str, limit: int) -> str:
    """Cut to ``limit`` display columns with an ellipsis — never a silent slice."""
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


def _live_width(width: int | None) -> int:
    """Caller-supplied width wins; otherwise the one width source in this package."""
    if width is not None:
        return width
    from kite.ui.status import terminal_width

    return terminal_width()


def _progress_bar(done: int, total: int, width: int = _BAR_COLUMNS) -> Text:
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


def _headline_item(todos: list[TodoItem], limit: int = _ACTIVE_MAX) -> str:
    """Show the task in flight, else the next one up — otherwise the line is static."""
    for wanted in ("in_progress", "pending"):
        item = next((i for i in todos if i.status == wanted), None)
        if item is not None:
            return _clip(item.content, limit)
    return ""


def render_task_row(
    item: TodoItem, *, tick: int = 0, width: int | None = None
) -> Text:
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
    # The badge rides at the row's right edge, so content gets what is left.
    room = _live_width(width) - cell_len(f"{GUTTER}{mark} ") - len(badge) - 2
    content = _clip(item.content, max(1, min(_ROW_MAX, room)))

    line = Text()
    line.append(f"{GUTTER}{mark} ", style=mark_style)
    line.append(content, style=text_style)
    line.append("  ", style="")
    line.append(badge, style=badge_style)
    line.append("\n")
    return line


def _render_header(
    todos: list[TodoItem], *, tick: int = 0, width: int | None = None
) -> Text:
    done = sum(1 for item in todos if item.status == "completed")
    total = len(todos)
    mark, mark_style = _plan_mark(todos)
    row_width = _live_width(width)

    head = f"{GUTTER}{mark} Tasks  {done}/{total}"
    room = row_width - cell_len(head)
    # `  · ` is the house separator around the item, so it is budgeted first.
    sep_columns = cell_len(_item_sep())
    bar_columns = 2 + _BAR_COLUMNS
    item_room = room - sep_columns - bar_columns
    # The bar is decoration; the count and the item in flight are the content.
    # If keeping the bar would squeeze the item below a readable stub, the bar
    # goes and the item keeps those columns.
    show_bar = bar_columns <= room and (
        not _headline_item(todos) or min(_ACTIVE_MAX, item_room) >= _MIN_ITEM_COLUMNS
    )
    active = _headline_item(
        todos, max(1, min(_ACTIVE_MAX, room - sep_columns - (bar_columns if show_bar else 0)))
    )

    t = Text()
    t.append(f"{GUTTER}{mark} ", style=mark_style)
    t.append("Tasks", style="kite.task")
    t.append(f"  {done}/{total}", style="kite.highlight")
    if show_bar:
        t.append("  ", style="")
        t.append_text(_progress_bar(done, total))
    # Nothing in flight and nothing pending: the bar alone tells the whole story.
    if active:
        t.append(_item_sep(), style="kite.muted")
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
