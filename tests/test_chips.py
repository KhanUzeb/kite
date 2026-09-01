"""Tool chips and task row rendering."""

from __future__ import annotations

from kite.ui.chips import render_plan_tasks, render_tool_chip, render_tool_chip_done
from kite.ui.state import TodoItem


def test_tool_chip_running_shows_ellipsis() -> None:
    text = render_tool_chip("edit", "src/foo.py", running=True)
    plain = text.plain
    assert "edit" in plain
    assert "src/foo.py" in plain
    assert "…" in plain


def test_tool_chip_done_warn() -> None:
    text = render_tool_chip_done("bash", ok=False, warn=True)
    assert "⚠" in text.plain
    assert "bash" in text.plain


def test_tool_chip_done_shows_diff_stat() -> None:
    text = render_tool_chip_done("edit", ok=True, meta="0.4s", added=125, deleted=21)
    assert "+125,-21" in text.plain
    assert "edit" in text.plain



def test_plan_tasks_shows_progress_and_badges() -> None:
    todos = [
        TodoItem("1", "write tests", "completed"),
        TodoItem("2", "run pytest", "in_progress"),
        TodoItem("3", "commit", "pending"),
    ]
    text = render_plan_tasks(todos, tick=0)
    plain = text.plain
    assert "Tasks" in plain
    assert "1/3" in plain
    assert "Done" in plain
    assert "In progress" in plain
    assert "To do" in plain
