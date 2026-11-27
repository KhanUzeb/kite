"""Long-running task UI regressions: live output and pinned-composer repaints.

Two defects surfaced when sustained tool/status output was driven through the
real render and poll paths:

1. ``tool_output`` / ``job_output`` are scrollback lines, but unlike ``todo``
   they painted while an answer row was still open. The live line was appended
   mid-sentence and the answer continuation lost its cell indent.
2. ``_sync_queue_count`` called ``state.touch()`` on every toolbar poll. With
   the composer pinned, ``touch()`` invalidates the prompt_toolkit app, so the
   toolbar repaint -> poll -> touch -> repaint loop ran continuously through a
   long turn instead of only on real queue transitions.

No sleeps, no provider calls: the terminal is a StringIO-backed Rich console
and the composer app is a counting stub.
"""

from __future__ import annotations

import re
import time
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from kite.agent.events import Event
from kite.ui.inbox import MessageInbox
from kite.ui.render import RunDisplay
from kite.ui.repl import ChatSession
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _display(width: int = 100) -> tuple[RunDisplay, StringIO]:
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    return RunDisplay(console, state=SessionUiState(), quiet=False), buf


def _plain(buf: StringIO) -> str:
    return _ANSI.sub("", buf.getvalue())


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("tool_output", {"line": "BACKGROUND-LINE", "tool": "bash"}),
        ("job_output", {"line": "BACKGROUND-LINE", "id": "j1"}),
    ],
)
def test_live_output_does_not_paint_inside_an_open_answer_row(kind: str, payload: dict) -> None:
    """A live output line owns its own row; the answer keeps its cell indent."""
    display, buf = _display()
    for event in (
        Event("agent_start", payload={"task": "long task", "provider": "p", "model": "m"}),
        Event("stream_start", payload={}),
        Event("stream_delta", payload={"text": "first half of the answer is open"}),
        Event(kind, payload=payload),
    ):
        display(event)
    assert display.state.activity_preview == "BACKGROUND-LINE"
    for event in (
        Event("stream_delta", payload={"text": "SECOND-HALF resumes here\n"}),
        Event("stream_end", payload={}),
        Event("agent_end", payload={"exit_status": "Submitted"}),
    ):
        display(event)
    display.close()
    rows = _plain(buf).splitlines()

    output_rows = [row for row in rows if "BACKGROUND-LINE" in row]
    assert len(output_rows) == 1, rows
    assert "first half" not in output_rows[0], "live output landed inside the answer row"

    tail = [row for row in rows if "SECOND-HALF" in row]
    assert len(tail) == 1, rows
    assert tail[0] == "  SECOND-HALF resumes here", repr(tail[0])
    assert display._channel is None and display._answer_col == 0  # noqa: SLF001


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("tool_output", {"line": "BACKGROUND-LINE", "tool": "bash"}),
        ("job_output", {"line": "BACKGROUND-LINE", "id": "j1"}),
    ],
)
def test_continuation_without_newline_keeps_cell_indent_after_live_output(kind: str, payload: dict) -> None:
    """A partial arriving after background output must paint its own gutter.

    ``_end_stream_line`` clears ``_need_prefix`` for a normal same-row
    continuation, so a scrollback line that replaced the row left the next
    partial starting at column 0. The newline case in the test above did not
    catch it because ``_write_answer_line`` supplies its own indent.
    """
    display, buf = _display()
    for event in (
        Event("agent_start", payload={"task": "long task", "provider": "p", "model": "m"}),
        Event("stream_start", payload={}),
        Event("stream_delta", payload={"text": "first half of the answer is open"}),
        Event(kind, payload=payload),
        # No trailing newline: this goes through _write_answer_partial.
        Event("stream_delta", payload={"text": "SECOND-HALF resumes here"}),
        Event("stream_end", payload={}),
        Event("agent_end", payload={"exit_status": "Submitted"}),
    ):
        display(event)
    display.close()
    rows = [row for row in _plain(buf).splitlines() if row.strip()]

    assert [row for row in rows if "BACKGROUND-LINE" in row] == [
        "BACKGROUND-LINE" if kind == "tool_output" else "[j1] BACKGROUND-LINE"
    ]
    assert [row for row in rows if "SECOND-HALF" in row] == ["  SECOND-HALF resumes here"], rows


def test_sustained_output_keeps_every_line_and_cleans_the_cursor() -> None:
    """A long interleaved run paints each live line once and leaves no open row."""
    display, buf = _display(width=80)
    display(Event("agent_start", payload={"task": "long", "provider": "p", "model": "m"}))
    display(Event("stream_start", payload={}))
    for i in range(40):
        display(Event("stream_delta", payload={"text": f"token-{i} "}))
        display(Event("tool_progress", payload={"tool": "bash", "elapsed_s": i, "hint": " — build"}))
        display(Event("tool_output", payload={"line": f"BUILD-LINE-{i}"}))
    display(Event("stream_delta", payload={"text": "ANSWER-END\n"}))
    display(Event("stream_end", payload={}))
    display(Event("turn_end", payload={"tools": 1}))
    display(Event("agent_end", payload={"exit_status": "Submitted", "submission": "## Done"}))
    display.close()

    rows = [row.strip() for row in _plain(buf).splitlines()]
    for i in range(40):
        assert rows.count(f"BUILD-LINE-{i}") == 1, f"BUILD-LINE-{i} missing or duplicated"
        assert not any(f"BUILD-LINE-{i}" in row and f"token-{i}" in row for row in rows)
    assert sum("ANSWER-END" in row for row in rows) == 1
    assert display._streaming is False and display._answer_col == 0  # noqa: SLF001
    assert display.state.running_label == "", "the turn boundary must clear the running line"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_toolbar_poll_only_invalidates_on_a_queue_transition(monkeypatch) -> None:
    """An idle pinned composer must not repaint itself on every 250 ms poll."""
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)

    invalidations: list[float] = []

    def _invalidate() -> None:
        invalidations.append(clock.now)

    chat = ChatSession.__new__(ChatSession)
    chat.state = SessionUiState(busy=True)
    chat.state._refresh = _invalidate  # noqa: SLF001
    chat._inbox = MessageInbox()
    chat._ui_queue = __import__("queue").SimpleQueue()
    chat.display = MagicMock()
    chat._approval_coordinator = SimpleNamespace(pending=None)
    chat._approval_wake_sent = False
    chat._prompt_app_running = lambda: False

    chat._inbox.enqueue("queue a follow-up")
    chat._toolbar_poll()
    assert len(invalidations) == 1, "the real queue transition still repaints"
    assert chat.state.queued == 1 and chat.state.queue_head == "queue a follow-up"

    clock.advance(0.05)
    chat._toolbar_poll()
    clock.advance(0.05)
    chat._toolbar_poll()
    assert len(invalidations) == 1, "unchanged queue counts must not invalidate the app"
    assert chat.state._touch_pending is False  # noqa: SLF001
