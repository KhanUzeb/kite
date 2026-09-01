"""Colourful task list rendering."""

from __future__ import annotations

from kite.ui.chips import render_plan_tasks
from kite.ui.state import TodoItem
from tests.conftest import strip_ansi


def test_plan_tasks_shows_progress_bar_and_colours() -> None:
    todos = [
        TodoItem(id="1", content="Inspect auth module", status="completed"),
        TodoItem(id="2", content="Add regression tests", status="in_progress"),
        TodoItem(id="3", content="Update docs", status="pending"),
    ]
    panel = render_plan_tasks(todos, tick=1)
    out = strip_ansi(panel.plain)
    assert "Tasks" in out
    assert "1/3" in out
    assert "Inspect auth module" in out
    assert "In progress" in out
    assert "To do" in out
