"""Task list rendering."""

from __future__ import annotations

from kite.ui.chips import render_plan_tasks
from kite.ui.state import TodoItem


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
