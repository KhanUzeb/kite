"""Streaming-path regressions: the answer stream must survive the v1.0.6 density work.

Four failure modes are locked here:

1. A scroll-printing event that lands while a streamed line is still open. The
   plan checklist (``todo`` -> ``print_plan``) had no ``_end_stream_line()``, so
   it painted straight into the middle of a half-written answer line - the
   visible symptom of "streaming broke". Every other scroll-printing handler
   ends the line first.
2. The scrollback line budget (``COLLAPSE_LINES`` == ``PREVIEW_LINES`` == 5) is a
   TOOL-BODY budget. It must never be applied to the answer path, or a long
   streamed answer gets truncated at 5 lines behind an ``/expand`` marker that
   does not apply to it.
3. A render failure used to be swallowed twice (``repl._drain_ui_queue`` and
   ``runtime._on_event``) with no traceback, no newline and no event redelivery,
   which together render as "no text showing, blank and black screen" and
   "text came but the agent stopped".
4. A failing handler must not leave the per-row stream state dirty, or every
   later line wraps against a cursor that no longer exists.
"""

from __future__ import annotations

import re
from io import StringIO

import pytest
from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME
from tests.conftest import strip_ansi

_HEAD = ("agent_start", {"task": "the task", "provider": "p", "model": "m"})
_START = ("stream_start", {})


def _display(width: int = 120) -> tuple[RunDisplay, StringIO]:
    """A RunDisplay whose console writes to an in-memory buffer."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    return RunDisplay(console, state=SessionUiState(), quiet=False), buf


def _feed(display: RunDisplay, events: list[tuple[str, dict]]) -> None:
    for kind, payload in events:
        display(Event(kind, payload=payload))


def test_todo_plan_checklist_does_not_paint_into_an_open_stream_line() -> None:
    """A ``todo`` event mid-line must not swallow the rest of the answer.

    ``print_plan`` used to rely on a leading blank ``self._print()`` to end the
    open stream row. Removing that blank (v1.0.6 density work) removed the only
    line break, so the checklist landed mid-sentence and the continuation lost
    its cell indent.
    """
    display, buf = _display()
    _feed(
        display,
        [
            *(_HEAD, _START),
            ("stream_delta", {"text": "first half of the answer is written"}),
            (
                "todo",
                {
                    "items": [
                        {"id": "1", "content": "read the module", "status": "completed"},
                        {"id": "2", "content": "cap the budget", "status": "in_progress"},
                    ]
                },
            ),
            ("stream_delta", {"text": "SECOND-HALF resumes here\n"}),
            ("stream_end", {}),
            ("turn_end", {}),
            ("agent_end", {}),
        ],
    )
    display.close()
    plain = strip_ansi(buf.getvalue())

    # The checklist paints on its own row, never appended to the answer line.
    task_rows = [ln for ln in plain.splitlines() if "Tasks" in ln]
    assert len(task_rows) == 1, plain
    assert "first half of the answer is written" not in task_rows[0], plain

    # Both halves of the answer survive, and the continuation keeps the cell
    # indent rather than snapping to column 0.
    assert "first half of the answer is written" in plain, plain
    tail = [ln for ln in plain.splitlines() if "SECOND-HALF" in ln]
    assert len(tail) == 1, plain
    assert tail[0].startswith("  "), repr(tail[0])
    assert tail[0] == "  SECOND-HALF resumes here", repr(tail[0])


def test_tool_end_between_stream_lines_leaves_no_column_state_behind() -> None:
    """A tool card closes the stream row; the next line still gets its indent.

    Also covers the ``echo_plan`` skip, where the plan body is deliberately not
    painted - a skipped body must not leave the row open either.
    """
    for tool, payload in (
        ("bash", {"tool": "bash", "ok": True, "output": "row a\nrow b\n"}),
        ("todo_write", {"tool": "todo_write", "ok": True, "output": "x\ny\n", "summary": "2 tasks"}),
    ):
        display, buf = _display()
        _feed(
            display,
            [
                *(_HEAD, _START),
                ("stream_delta", {"text": "alpha beta gamma delta epsilon zeta\n"}),
                ("tool_start", {"tool": tool, "arguments": {}}),
                ("tool_end", payload),
                ("stream_delta", {"text": "next streamed line after the tool card\n"}),
                ("stream_end", {}),
                ("turn_end", {}),
                ("agent_end", {}),
            ],
        )
        display.close()
        plain = strip_ansi(buf.getvalue())
        assert display._answer_col == 0, (tool, display._answer_col)
        assert display._streaming is False, tool
        tail = [ln for ln in plain.splitlines() if "next streamed line" in ln]
        assert tail == ["  next streamed line after the tool card"], (tool, tail)


def test_long_streamed_answer_is_not_capped_by_the_scrollback_line_budget() -> None:
    """40 streamed paragraphs all reach the screen, with no /expand marker.

    ``COLLAPSE_LINES`` was 12 and is now ``PREVIEW_LINES`` (5). It is a
    tool-body budget; if any part of the answer path reaches it, a normal long
    answer loses everything past the 5th line.
    """
    display, buf = _display()
    _feed(
        display,
        [
            *(_HEAD, _START),
            *[
                ("stream_delta", {"text": f"Paragraph {i:02d} explains the streamed answer.\n"})
                for i in range(40)
            ],
            ("stream_end", {}),
            ("turn_end", {}),
            ("agent_end", {}),
        ],
    )
    display.close()
    plain = strip_ansi(buf.getvalue())

    found = re.findall(r"Paragraph (\d\d)", plain)
    assert sorted(set(found)) == [f"{i:02d}" for i in range(40)], found
    # An answer is not a collapsible block: no marker, and nothing dropped.
    assert "/expand" not in plain, plain
    assert "lines" not in plain, plain


def test_oversized_fenced_block_shows_the_truncation_marker() -> None:
    """Past the fence budget the block stops, says so, and still closes."""
    display, buf = _display()
    _feed(
        display,
        [
            *(_HEAD, _START),
            ("stream_delta", {"text": "```python\n"}),
            *[("stream_delta", {"text": f"code row {i:03d} " + "x" * 40 + "\n"}) for i in range(200)],
            ("stream_delta", {"text": "```\n"}),
            ("stream_end", {}),
            ("turn_end", {}),
            ("agent_end", {}),
        ],
    )
    display.close()
    plain = strip_ansi(buf.getvalue())

    # Explicit marker, exactly once, rather than a silent dump or a vanish.
    assert plain.count("truncated code block") == 1, plain
    # The budget is honoured: the tail of the fence is not printed.
    assert "code row 199" not in plain, plain
    assert "code row 073" in plain, plain
    # The fence still closes, so the rest of the answer renders normally.
    assert "```" in plain.split("truncated code block", 1)[1], plain


# --- invisible render failures -------------------------------------------------
#
# A render bug must never kill a run - that is why both swallow sites catch
# everything. What made that undebuggable is what they threw away: the event was
# already popped by get_nowait() (so it was gone for good), a partial write could
# leave the cursor mid-row with no newline (which reads as a blank/black screen),
# and no traceback was recorded anywhere. These lock the fix: still non-fatal,
# no longer invisible.


def _boom_handler(payload: dict) -> None:
    """A handler that provably raises, installed in place of a real one."""
    raise ValueError(f"render blew up on {sorted(payload)}")


@pytest.fixture
def drain_harness(workspace, kite_home, monkeypatch):
    """Real queue/display behavior without startup network or background warmers."""
    from kite.ui.repl import ChatSession

    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)

    session = ChatSession(cwd=str(workspace))
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=True, theme=KITE_THEME)
    session.console = console
    session.display.console = console
    session._busy = True
    yield session, buf
    session.display.close()


def _queue(session, *events: tuple[str, dict]) -> None:
    for kind, payload in events:
        session._ui_queue.put(Event(kind, payload=payload))


_PARTIAL = "half-written answer text long enough to reach the terminal"


def test_drain_survives_a_raising_handler_and_says_so(drain_harness) -> None:
    """A render failure must not kill the turn, and must not be invisible.

    Covers all four properties at once, because they were one bug: no
    propagation, a visible one-line notice, a closed row, and a retrievable
    traceback.
    """
    session, buf = drain_harness
    # The handler that will fail, installed the way the registry calls it.
    session.display._event_handlers["tool_end"] = _boom_handler  # noqa: SLF001
    _queue(
        session,
        ("agent_start", {"task": "t", "provider": "p", "model": "m"}),
        ("stream_start", {}),
        ("stream_delta", {"text": _PARTIAL}),
        ("tool_end", {"tool": "bash", "ok": True, "output": "x"}),
    )

    # (a) the drain does not propagate - this is the property that must survive.
    session._drain_ui_queue()

    plain = strip_ansi(buf.getvalue())

    # (b) one visible line, naming the failure and how to see the detail.
    assert plain.count("ui event failed") == 1, plain
    assert "output may be incomplete" in plain, plain
    assert "/trace" in plain, plain

    # (c) no half-written line: the text before the failure survived AND the
    # output ends on a newline, so the next paint starts on a clean row.
    assert _PARTIAL in plain, plain
    assert plain.endswith("\n"), repr(plain[-80:])

    # (d) the traceback is recorded where /trace reads it.
    assert "Traceback (most recent call last)" in session.state.last_trace
    assert "ValueError" in session.state.last_trace
    assert "render blew up" in session.state.last_trace
    assert "ui event failed" in session.state.last_error.lower()

    # And the row state is clean, so the next line is not corrupted.
    display = session.display
    assert display._answer_col == 0  # noqa: SLF001
    assert display._streaming is False  # noqa: SLF001
    assert display._answer_hold == ""  # noqa: SLF001

    # The handler is restored: the display heals and the turn carries on.
    del session.display._event_handlers["tool_end"]  # noqa: SLF001
    _queue(
        session,
        ("stream_delta", {"text": "next streamed line after the failure\n"}),
        ("stream_end", {}),
        ("turn_end", {}),
        ("agent_end", {}),
    )
    session._drain_ui_queue()
    session.display.close()

    plain = strip_ansi(buf.getvalue())
    tail = [ln for ln in plain.splitlines() if "next streamed line" in ln]
    # The line is on its own row, inside the cell gutter. ``_did_first_line`` is
    # deliberately NOT reset by the failure path: the answer was already past its
    # first line, so this is a continuation and must not re-arm the "•" marker.
    assert len(tail) == 1, tail
    assert tail[0] == "  next streamed line after the failure", repr(tail[0])


def test_drain_reports_once_and_counts_repeats(drain_harness) -> None:
    """A per-token bug must not scroll hundreds of identical notices."""
    session, buf = drain_harness
    session.display._event_handlers["tool_end"] = _boom_handler  # noqa: SLF001
    for _ in range(5):
        _queue(session, ("tool_end", {"tool": "bash", "ok": True, "output": "x"}))
    session._drain_ui_queue()

    plain = strip_ansi(buf.getvalue())
    assert plain.count("ui event failed") == 1, plain
    assert session._ui_failures == 5  # noqa: SLF001
    # Repeats are still counted where the user can see them.
    assert "5x" in session.state.flash, session.state.flash

    # A new turn gets a fresh notice rather than only a flash.
    session._begin_turn_state("next task")  # noqa: SLF001
    assert session._ui_failures == 0  # noqa: SLF001
    _queue(session, ("tool_end", {"tool": "bash", "ok": True, "output": "y"}))
    session._drain_ui_queue()
    assert strip_ansi(buf.getvalue()).count("ui event failed") == 2


def test_drain_reports_a_flushing_stream_failure_too(drain_harness) -> None:
    """The coalescer flush is the other swallow site; it is now visible too."""
    session, buf = drain_harness

    def boom() -> None:
        raise RuntimeError("flush exploded")

    session.display.flush_due_streams = boom  # type: ignore[method-assign]
    _queue(session, ("stream_delta", {"text": _PARTIAL}))

    session._drain_ui_queue()  # must not propagate

    plain = strip_ansi(buf.getvalue())
    assert plain.count("ui stream flush failed") == 1, plain
    assert "RuntimeError" in session.state.last_trace
    assert "flush exploded" in session.state.last_trace


def test_runtime_listener_failure_is_non_fatal_and_recorded(workspace, kite_home) -> None:
    """A frontend that raises must not break the agent - or vanish.

    ``_on_event`` catches listener exceptions so one broken UI cannot abort a
    run, and it must keep doing that. The bare ``continue`` it replaced threw
    away the only evidence that a listener - very often the display itself -
    had died mid-run.
    """
    from kite.agent.runtime import AgentRuntime, RuntimeOptions

    runtime = AgentRuntime(RuntimeOptions(cwd=str(workspace)))
    reached: list[str] = []

    def bad(_event: Event) -> None:
        raise RuntimeError("listener exploded")

    def good(event: Event) -> None:
        reached.append(event.kind)

    runtime.subscribe(bad)
    runtime.subscribe(good)

    # Non-fatal: no raise, and the other listener still gets every event.
    runtime._on_event(Event("stream_delta", payload={"text": "x"}))  # noqa: SLF001
    runtime._on_event(Event("turn_end", payload={}))  # noqa: SLF001
    assert reached == ["stream_delta", "turn_end"]

    # Recorded, with the traceback, on the runtime. The record names the event
    # kind that hit the listener, so a report says WHICH event died.
    assert runtime._listener_errors == 2  # noqa: SLF001
    assert "RuntimeError" in runtime.last_listener_error
    assert "listener exploded" in runtime.last_listener_error
    assert "Traceback (most recent call last)" in runtime.last_listener_error
    # The newest record is kept; the FIRST of the turn is parked for the frontend.
    assert "turn_end" in runtime.last_listener_error
    parked = runtime.take_listener_error()
    assert "stream_delta" in parked, parked
    assert runtime.take_listener_error() == ""  # consumed by the read

    # A new turn re-arms the one-notice budget.
    runtime.begin_turn()
    assert runtime._listener_errors == 0  # noqa: SLF001
    runtime._on_event(Event("turn_end", payload={}))  # noqa: SLF001
    assert runtime.take_listener_error()
    # The last record is retained after the turn's notice was taken.
    assert runtime.last_listener_error


def _harness_with_parked_listener_error(kind: str, cwd: str) -> object:
    """A Harness whose runtime has one listener failure waiting to be reported."""
    from kite.agent.harness import Harness, HarnessConfig

    harness = Harness(config=HarnessConfig(cwd=cwd))
    harness.subscribe(lambda _e: None)  # builds the runtime
    runtime = harness._runtime  # noqa: SLF001
    assert runtime is not None
    try:
        raise RuntimeError("listener exploded")
    except RuntimeError:
        # Exactly what _on_event's handler does: record the live exception.
        runtime._record_listener_failure(lambda _e: None, Event(kind, payload={}))  # noqa: SLF001
    return harness


def test_repl_surfaces_a_listener_failure_at_turn_end(drain_harness) -> None:
    """The parked record becomes a visible line once the turn is over."""
    session, buf = drain_harness
    harness = _harness_with_parked_listener_error("stream_delta", session.cwd)

    session._report_listener_failure(harness)  # noqa: SLF001

    plain = strip_ansi(buf.getvalue())
    assert plain.count("event listener failed") == 1, plain
    assert "/trace" in plain, plain
    assert "Traceback" in session.state.last_trace
    assert "listener exploded" in session.state.last_trace
    # Reported once: the second call has nothing left to report.
    session._report_listener_failure(harness)  # noqa: SLF001
    assert strip_ansi(buf.getvalue()).count("event listener failed") == 1

    # A harness with no runtime, or no parked error, is simply a no-op.
    session._report_listener_failure(object())  # noqa: SLF001
    assert strip_ansi(buf.getvalue()) == plain


def test_repl_listener_notice_does_not_clobber_a_real_agent_trace(drain_harness) -> None:
    """An Error status line has a better trace than a listener failure."""
    session, _buf = drain_harness
    session.state.last_trace = "REAL AGENT TRACEBACK"

    session._report_listener_failure(  # noqa: SLF001
        _harness_with_parked_listener_error("turn_end", session.cwd)
    )

    assert session.state.last_trace == "REAL AGENT TRACEBACK"


def test_streamed_cells_preserve_unicode_and_chunk_separators() -> None:
    from rich.cells import cell_len

    from kite.ui.theme import glyph

    samples = (
        "word boundaries survive small chunks. " * 12,
        "路径界面 emoji 🙂 cafe\u0301 " * 12,
        "https://example.com/" + "界" * 140 + " end",
    )
    for width in (50, 60, 80, 120):
        for text in samples:
            for size in (5, len(text)):
                display, buf = _display(width)
                for offset in range(0, len(text), size):
                    display(Event("stream_delta", payload={"text": text[offset:offset + size]}))
                display.close()
                rows = strip_ansi(buf.getvalue()).splitlines()
                assert all(cell_len(row) <= width for row in rows), (width, size, rows)
                assert all(row.startswith("  ") for row in rows[1:]), (width, size, rows)
                recovered = "".join(rows).replace(glyph("agent"), "", 1)
                assert "".join(recovered.split()) == "".join(text.split())
                if text.startswith("word"):
                    assert recovered.split() == text.split()


def test_deferred_answer_and_live_reasoning_keep_the_whole_stream() -> None:
    display, buf = _display()
    display.state.busy = True
    display.composer_owns_input = True
    parts = [f"part-{i:04d}\n" for i in range(2105)]
    for part in parts:
        display(Event("stream_delta", payload={"text": part}))
    display.finish_composer_turn({"exit_status": "Submitted"})
    plain = strip_ansi(buf.getvalue())
    assert re.findall(r"part-\d{4}", plain) == [part.strip() for part in parts]
    assert display._deferred_answer_parts == []

    display.state.thinking_expanded = False
    display.state.last_thinking = "previous completed reasoning"
    for part in ("look ", "at ", "the tests"):
        display(Event("stream_reasoning", payload={"text": part}))
    assert display.state.last_thinking == "previous completed reasoning"
    assert display.thinking_text() == "look at the tests"
    display(Event("stream_end", payload={}))
    assert display.state.last_thinking == "look at the tests"
    assert display.thinking_text() == "look at the tests"
    display.close()

    live, live_buf = _display()
    reasoning = "unique-reasoning-token " + "detail " * 20
    live(Event("stream_reasoning", payload={"text": reasoning}))
    live(Event("stream_reasoning", payload={"text": "last-reasoning-token"}))
    live(Event("stream_delta", payload={"text": "final answer"}))
    live.close()
    painted = strip_ansi(live_buf.getvalue())
    assert painted.count("unique-reasoning-token") == 1
    assert painted.count("last-reasoning-token") == 1
    assert painted.index("last-reasoning-token") < painted.index("final answer")