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

from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import COLLAPSE_LINES, KITE_THEME, PREVIEW_LINES
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


def _stream(lines: list[str]) -> list[tuple[str, dict]]:
    return _HEAD, _START


def _c_test_todo_plan_checklist_does_not_paint_into_an_open_stream_line() -> None:
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
            *_stream([]),
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


def _c_test_tool_end_between_stream_lines_leaves_no_column_state_behind() -> None:
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
                *_stream([]),
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


def _c_test_long_streamed_answer_is_not_capped_by_the_scrollback_line_budget() -> None:
    """40 streamed paragraphs all reach the screen, with no /expand marker.

    ``COLLAPSE_LINES`` was 12 and is now ``PREVIEW_LINES`` (5). It is a
    tool-body budget; if any part of the answer path reaches it, a normal long
    answer loses everything past the 5th line.
    """
    assert COLLAPSE_LINES == PREVIEW_LINES == 5
    display, buf = _display()
    _feed(
        display,
        [
            *_stream([]),
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


def _c_test_tool_body_still_gets_the_preview_budget() -> None:
    """Control for the test above: the budget applies to tool bodies only."""
    display, buf = _display()
    display.state.expanded_all = False
    _feed(
        display,
        [
            ("tool_end", {"tool": "bash", "ok": True,
                          "output": "\n".join(f"result line {i:02d}" for i in range(30))}),
        ],
    )
    display.close()
    plain = strip_ansi(buf.getvalue())
    body = [ln for ln in plain.splitlines() if "result line" in ln]
    assert len(body) == PREVIEW_LINES, body
    assert "result line 29" not in plain and "/expand" in plain


def _c_test_oversized_fenced_block_shows_the_truncation_marker() -> None:
    """Past the fence budget the block stops, says so, and still closes."""
    display, buf = _display()
    _feed(
        display,
        [
            *_stream([]),
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


def _c_test_streamed_answer_reaches_the_screen_through_output_view_uncapped() -> None:
    """``_collapse_text`` must not sit in the answer path.

    ``render_output_block``'s default ``limit`` became ``PREVIEW_LINES``; the
    answer writer bypasses it entirely, and this locks that bypass.
    """
    from kite.ui.output_view import render_output_block

    display, buf = _display()
    _feed(
        display,
        [
            *_stream([]),
            *[("stream_delta", {"text": f"answer row {i:02d} padding\n"}) for i in range(20)],
            ("stream_end", {}),
            ("turn_end", {}),
            ("agent_end", {}),
        ],
    )
    display.close()
    plain = strip_ansi(buf.getvalue())
    assert len(re.findall(r"answer row \d\d", plain)) == 20, plain

    # The block renderer is still capped - for its actual callers.
    capped = strip_ansi(render_output_block("\n".join(f"row {i}" for i in range(20)),
                                           expanded=False).plain)
    assert len(capped.splitlines()) == PREVIEW_LINES + 1, capped


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


def _drain_harness(tmp_path, monkeypatch, width: int = 100):
    """A real ChatSession with its console pointed at an in-memory buffer.

    Mirrors ``tests/test_repl_exit._quiet_session`` (same four patches) and then
    swaps in a recording console, so ``_drain_ui_queue`` runs exactly as the REPL
    runs it - through the real ``_ui_queue`` and the real ``RunDisplay``.
    """
    from kite.ui.repl import ChatSession

    monkeypatch.setattr(ChatSession, "_schedule_release_check_legacy", lambda self: None)
    monkeypatch.setattr(ChatSession, "_prewarm_composer", lambda self: None)
    monkeypatch.setattr(ChatSession, "_startup_banner", lambda self: None)
    monkeypatch.setattr(ChatSession, "_maybe_prompt_project_trust", lambda self: None)
    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)

    session = ChatSession(cwd=str(tmp_path))
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    session.console = console
    session.display.console = console
    session._busy = True
    return session, buf


def _queue(session, *events: tuple[str, dict]) -> None:
    for kind, payload in events:
        session._ui_queue.put(Event(kind, payload=payload))


_PARTIAL = "half-written answer text long enough to reach the terminal"


def _c_test_drain_survives_a_raising_handler_and_says_so(tmp_path, monkeypatch) -> None:
    """A render failure must not kill the turn, and must not be invisible.

    Covers all four properties at once, because they were one bug: no
    propagation, a visible one-line notice, a closed row, and a retrievable
    traceback.
    """
    session, buf = _drain_harness(tmp_path, monkeypatch)
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


def _c_test_drain_leaves_the_next_stream_line_correct_after_a_failure(
    tmp_path, monkeypatch
) -> None:
    """A failure must not cascade: the next streamed line still gets its indent.

    Without the state reset the phantom ``_answer_col`` makes the following line
    wrap and indent against a cursor that is gone, which is how one bad event
    turned into a whole broken turn.
    """
    session, buf = _drain_harness(tmp_path, monkeypatch)
    session.display._event_handlers["tool_end"] = _boom_handler  # noqa: SLF001
    _queue(
        session,
        ("agent_start", {"task": "t", "provider": "p", "model": "m"}),
        ("stream_start", {}),
        ("stream_delta", {"text": _PARTIAL}),
        ("tool_end", {"tool": "bash", "ok": True, "output": "x"}),
    )
    session._drain_ui_queue()

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


def _c_test_drain_reports_once_and_counts_repeats(tmp_path, monkeypatch) -> None:
    """A per-token bug must not scroll hundreds of identical notices."""
    session, buf = _drain_harness(tmp_path, monkeypatch)
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


def _c_test_drain_reports_a_flushing_stream_failure_too(tmp_path, monkeypatch) -> None:
    """The coalescer flush is the other swallow site; it is now visible too."""
    session, buf = _drain_harness(tmp_path, monkeypatch)

    def boom() -> None:
        raise RuntimeError("flush exploded")

    session.display.flush_due_streams = boom  # type: ignore[method-assign]
    _queue(session, ("stream_delta", {"text": _PARTIAL}))

    session._drain_ui_queue()  # must not propagate

    plain = strip_ansi(buf.getvalue())
    assert plain.count("ui stream flush failed") == 1, plain
    assert "RuntimeError" in session.state.last_trace
    assert "flush exploded" in session.state.last_trace


def _c_test_runtime_listener_failure_is_non_fatal_and_recorded() -> None:
    """A frontend that raises must not break the agent - or vanish.

    ``_on_event`` catches listener exceptions so one broken UI cannot abort a
    run, and it must keep doing that. The bare ``continue`` it replaced threw
    away the only evidence that a listener - very often the display itself -
    had died mid-run.
    """
    from kite.agent.runtime import AgentRuntime, RuntimeOptions

    runtime = AgentRuntime(RuntimeOptions(cwd="."))
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


def _harness_with_parked_listener_error(kind: str) -> object:
    """A Harness whose runtime has one listener failure waiting to be reported."""
    from kite.agent.harness import Harness

    harness = Harness()
    harness.subscribe(lambda _e: None)  # builds the runtime
    runtime = harness._runtime  # noqa: SLF001
    assert runtime is not None
    try:
        raise RuntimeError("listener exploded")
    except RuntimeError:
        # Exactly what _on_event's handler does: record the live exception.
        runtime._record_listener_failure(lambda _e: None, Event(kind, payload={}))  # noqa: SLF001
    return harness


def _c_test_repl_surfaces_a_listener_failure_at_turn_end(tmp_path, monkeypatch) -> None:
    """The parked record becomes a visible line once the turn is over."""
    session, buf = _drain_harness(tmp_path, monkeypatch)
    harness = _harness_with_parked_listener_error("stream_delta")

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


def _c_test_repl_listener_notice_does_not_clobber_a_real_agent_trace(
    tmp_path, monkeypatch
) -> None:
    """An Error status line has a better trace than a listener failure."""
    session, _buf = _drain_harness(tmp_path, monkeypatch)
    session.state.last_trace = "REAL AGENT TRACEBACK"

    session._report_listener_failure(  # noqa: SLF001
        _harness_with_parked_listener_error("turn_end")
    )

    assert session.state.last_trace == "REAL AGENT TRACEBACK"


def _c_test_streamed_paragraph_wraps_inside_the_gutter_at_narrow_widths() -> None:
    """Width 60 and 80: no row overruns, and continuations keep the indent.

    ``_wrap_width`` returns 0 when the width is unknown and the answer path then
    relies on Rich, which wraps to column 0 and loses the gutter. At a known
    width the wrap must happen here instead - for one big chunk and for a
    paragraph trickled in as many small ones (the real token stream).
    """
    paragraph = (
        "This is a long streamed paragraph that must wrap inside the cell gutter "
        "and keep a correct continuation indent on every wrapped row, which is the "
        "whole point of the wrap pass, and it keeps going for a while to force "
        "several wraps in a row. "
    )
    for width in (60, 80):
        for chunks in (1, 7):
            display, buf = _display(width=width)
            _feed(
                display,
                [
                    *_stream([]),
                    *_streamed_chunks(paragraph * 3, chunks),
                    ("stream_end", {}),
                    ("turn_end", {}),
                    ("agent_end", {}),
                ],
            )
            display.close()
            plain = strip_ansi(buf.getvalue())
            # Only the streamed answer, not the user cell the run also prints.
            body = [
                ln
                for ln in plain.splitlines()
                if "streamed paragraph" in ln or "continuation indent" in ln
                or "wrap pass" in ln or "several wraps" in ln or "keeps going" in ln
            ]
            assert body, (width, chunks, plain)
            # The paragraph really did wrap, so the width check below is real.
            assert len(body) > 4, (width, chunks, body)
            # No row overruns the terminal width (the hard wrap is the bug).
            over = [ln for ln in body if len(ln) > width]
            assert not over, (width, chunks, over[:2])
            # Every continuation row is indented, never back at column 0.
            cont = body[1:]
            assert all(ln.startswith("  ") for ln in cont), (width, chunks, cont[:3])
            # No text is lost by wrapping.
            joined = " ".join(body)
            for word in ("gutter", "continuation", "several", "wraps"):
                assert word in joined, (width, chunks, word)


def _streamed_chunks(text: str, chunks: int) -> list[tuple[str, dict]]:
    step = max(1, len(text) // chunks)
    return [("stream_delta", {"text": text[i : i + step]}) for i in range(0, len(text), step)]


def test_batch_00() -> None:
    """Consolidated (bodies unchanged): stream-vs-tool interleaving."""
    _c_test_todo_plan_checklist_does_not_paint_into_an_open_stream_line()
    _c_test_tool_end_between_stream_lines_leaves_no_column_state_behind()
    _c_test_long_streamed_answer_is_not_capped_by_the_scrollback_line_budget()
    _c_test_tool_body_still_gets_the_preview_budget()
    _c_test_oversized_fenced_block_shows_the_truncation_marker()
    _c_test_streamed_answer_reaches_the_screen_through_output_view_uncapped()


def test_batch_01(tmp_path, monkeypatch) -> None:
    """Consolidated (bodies unchanged): drain+flush."""
    _t0 = tmp_path / "b1_0"
    _t0.mkdir(parents=True, exist_ok=True)
    _c_test_drain_survives_a_raising_handler_and_says_so(tmp_path=_t0, monkeypatch=monkeypatch)
    _t1 = tmp_path / "b1_1"
    _t1.mkdir(parents=True, exist_ok=True)
    _c_test_drain_leaves_the_next_stream_line_correct_after_a_failure(tmp_path=_t1, monkeypatch=monkeypatch)
    _t2 = tmp_path / "b1_2"
    _t2.mkdir(parents=True, exist_ok=True)
    _c_test_drain_reports_once_and_counts_repeats(tmp_path=_t2, monkeypatch=monkeypatch)
    _t3 = tmp_path / "b1_3"
    _t3.mkdir(parents=True, exist_ok=True)
    _c_test_drain_reports_a_flushing_stream_failure_too(tmp_path=_t3, monkeypatch=monkeypatch)


def test_batch_02(tmp_path, monkeypatch) -> None:
    """Consolidated (bodies unchanged): listener-plumbing+narrow-wrap."""
    _c_test_runtime_listener_failure_is_non_fatal_and_recorded()
    _t0 = tmp_path / "b2_0"
    _t0.mkdir(parents=True, exist_ok=True)
    _c_test_repl_surfaces_a_listener_failure_at_turn_end(tmp_path=_t0, monkeypatch=monkeypatch)
    _t1 = tmp_path / "b2_1"
    _t1.mkdir(parents=True, exist_ok=True)
    _c_test_repl_listener_notice_does_not_clobber_a_real_agent_trace(tmp_path=_t1, monkeypatch=monkeypatch)
    _c_test_streamed_paragraph_wraps_inside_the_gutter_at_narrow_widths()