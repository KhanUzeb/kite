"""Scrollback density — the plan prints once, big bodies get a preview budget."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.diff import make_unified_diff
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME, PREVIEW_LINES
from tests.conftest import strip_ansi


def _display(width: int = 120) -> tuple[RunDisplay, StringIO]:
    """A RunDisplay whose console writes to an in-memory buffer."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    return RunDisplay(console, state=SessionUiState(), quiet=False), buf


def _items() -> list[dict[str, str]]:
    return [
        {"id": "1", "content": "read the diff module", "status": "completed"},
        {"id": "2", "content": "cap the preview budget", "status": "in_progress"},
        {"id": "3", "content": "run the full suite", "status": "pending"},
    ]


def _big_diff(rows: int = 60) -> str:
    before = "".join(f"line {i}\n" for i in range(rows))
    after = "".join(f"line {i} edited\n" for i in range(rows))
    return make_unified_diff("src/app.py", before, after)


def _diff_body_rows(plain: str) -> list[str]:
    """Rendered diff content rows, excluding the stat header and the hint row.

    Content rows carry a line-number gutter before the bar, so look for the bar
    anywhere in the row rather than at its left edge.
    """
    rows = []
    for line in plain.splitlines():
        body = line.strip()
        if "\u250a" not in body:  # the diff bar
            continue
        if "@@" in body or "/expand" in body or "src/app.py" in body:
            continue
        rows.append(body)
    return rows


def test_todo_tool_call_prints_the_plan_once_and_never_echoes_its_body() -> None:
    """todo_write painted the checklist, a start card, a done card, AND the JSON.

    The plan checklist is the UI for the todo tools; their result payload is the
    same items over again, so the tool must not echo itself.
    """
    plan_items = _items()
    display, buf = _display()
    display(Event("todo", payload={"items": plan_items}))
    display(Event("tool_start", payload={"tool": "todo_write", "arguments": {"items": plan_items}}))
    display(
        Event(
            "tool_end",
            payload={
                "tool": "todo_write",
                "ok": True,
                "duration_ms": 3,
                "preview": "completed read the diff module",
                "summary": "3 tasks updated",
                "output": "\n".join(f"{i['status']:12} {i['content']}" for i in plan_items),
            },
        )
    )
    display.close()
    plain = strip_ansi(buf.getvalue())

    # The checklist paints exactly once, not once per paint path.
    assert plain.count("Tasks") == 1, plain
    assert plain.count("cap the preview budget") == 1, plain
    # The tool body is that same list — it must never be echoed back.
    assert "completed  read the diff module" not in plain, plain
    assert "in_progress  cap the preview budget" not in plain
    assert "pending     run the full suite" not in plain
    # The preview and summary are cut from that body, so they go too.
    assert "3 tasks updated" not in plain
    assert "completed read the diff module" not in plain
    # The done card still reports the call; the start card does not print.
    assert "todo_write" in plain and "3ms" in plain
    assert "executing" not in plain

    # todo_read returns the same payload and is suppressed the same way.
    read_buf = StringIO()
    reader = RunDisplay(
        Console(file=read_buf, width=120, force_terminal=True, theme=KITE_THEME),
        state=SessionUiState(),
    )
    reader(Event("todo", payload={"items": plan_items}))
    reader(Event("tool_start", payload={"tool": "todo_read", "arguments": {}}))
    reader(
        Event(
            "tool_end",
            payload={
                "tool": "todo_read",
                "ok": True,
                "output": "\n".join(i["content"] for i in plan_items),
            },
        )
    )
    reader.close()
    read_plain = strip_ansi(read_buf.getvalue())
    assert read_plain.count("Tasks") == 1, read_plain
    assert read_plain.count("cap the preview budget") == 1, read_plain
    assert "executing" not in read_plain

    # A failing plan tool still shows the error body — suppression is not blanket.
    err_buf = StringIO()
    broken = RunDisplay(
        Console(file=err_buf, width=120, force_terminal=True, theme=KITE_THEME),
        state=SessionUiState(),
    )
    broken(
        Event(
            "tool_end",
            payload={
                "tool": "todo_write",
                "ok": False,
                "error": "invalid status 'nearly'",
                "output": "invalid status 'nearly'",
            },
        )
    )
    broken.close()
    assert "invalid status" in strip_ansi(err_buf.getvalue())


def test_large_tool_output_body_is_capped_at_the_preview_budget() -> None:
    """A 30-line body shows 5 lines plus the marker, not the whole dump."""
    assert PREVIEW_LINES == 5
    display, buf = _display()
    display.state.expanded_all = False
    output = "\n".join(f"result line {i:02d}" for i in range(30))
    display(Event("tool_end", payload={"tool": "bash", "ok": True, "output": output}))
    display.close()
    plain = strip_ansi(buf.getvalue())

    body = [ln for ln in plain.splitlines() if "result line" in ln]
    assert len(body) == PREVIEW_LINES, body
    assert "result line 00" in plain and "result line 04" in plain
    assert "result line 05" not in plain and "result line 29" not in plain
    # The overflow marker is what makes the truncation legible.
    assert "/expand" in plain and "+25 lines" in plain


def test_tool_end_diff_body_is_capped_but_keeps_stat_and_hint() -> None:
    """Scroll-print diffs get 5 lines, not the 40-line approval budget."""
    assert PREVIEW_LINES == 5
    display, buf = _display()
    display.state.expanded_all = False
    display(Event("tool_end", payload={"tool": "edit", "ok": True, "diff": _big_diff()}))
    display.close()
    plain = strip_ansi(buf.getvalue())

    # The stat header is metadata and always paints.
    assert "src/app.py" in plain
    assert "+60,-60" in plain
    # The body is capped, and the remainder is announced rather than dropped.
    body = _diff_body_rows(plain)
    assert 0 < len(body) <= PREVIEW_LINES + 2, body
    assert "line 5" not in "".join(body)
    assert "/expand" in plain

    # A diff event is capped the same way.
    event_buf = StringIO()
    event_display = RunDisplay(
        Console(file=event_buf, width=120, force_terminal=True, theme=KITE_THEME),
        state=SessionUiState(),
    )
    event_display.state.expanded_all = False
    event_display(Event("diff", payload={"path": "src/app.py", "diff": _big_diff()}))
    event_display.close()
    event_plain = strip_ansi(event_buf.getvalue())
    assert "src/app.py" in event_plain and "+60,-60" in event_plain
    assert "/expand" in event_plain
    assert len(_diff_body_rows(event_plain)) <= PREVIEW_LINES + 2
    assert "line 50" not in event_plain

    # Truncating mid -/+ pair must not crash the renderer.
    split_buf = StringIO()
    split_display = RunDisplay(
        Console(file=split_buf, width=120, force_terminal=True, theme=KITE_THEME),
        state=SessionUiState(),
    )
    split_display.state.expanded_all = False
    split_display(
        Event(
            "tool_end",
            payload={
                "tool": "edit",
                "ok": True,
                # A pure deletion: every -/+ pair is left unpaired once the cap cuts.
                "diff": make_unified_diff("q.py", "".join(f"l{i}\n" for i in range(30)), ""),
            },
        )
    )
    split_display.close()
    assert "/expand" in strip_ansi(split_buf.getvalue())


def test_print_plan_is_a_no_op_when_the_todo_list_is_unchanged() -> None:
    """The key guard stops a re-render of an identical checklist."""
    display, buf = _display()
    display.state.set_todos(_items())
    display.print_plan()
    after_first = buf.getvalue()
    assert after_first.strip(), "the first paint must reach the screen"
    display.print_plan()
    display.print_plan()
    assert buf.getvalue() == after_first, "an unchanged plan must not repaint"

    # A changed status is a real update and does repaint.
    display.state.set_todos([{**_items()[1], "status": "completed"}])
    display.print_plan()
    assert strip_ansi(buf.getvalue()).count("Tasks") == 2, strip_ansi(buf.getvalue())

    # No todos means nothing to print at all.
    empty_buf = StringIO()
    empty = RunDisplay(
        Console(file=empty_buf, width=120, force_terminal=True, theme=KITE_THEME),
        state=SessionUiState(),
    )
    empty.print_plan()
    assert empty_buf.getvalue() == ""