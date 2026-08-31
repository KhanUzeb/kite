"""RunDisplay event handling (no TTY)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME


def _display() -> tuple[StringIO, RunDisplay]:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    return buf, RunDisplay(console, state=SessionUiState(), quiet=False)


def test_warning_event_prints_muted_line() -> None:
    buf, display = _display()
    display(Event("warning", payload={"message": "filesystem mount failed"}))
    out = buf.getvalue()
    assert "filesystem mount failed" in out


def test_idle_verification_is_silent() -> None:
    buf, display = _display()
    display(Event("artifact", payload={"status": "idle", "artifact_count": 0, "diff_count": 0, "gaps": [], "artifacts": []}))
    display(
        Event(
            "agent_end",
            payload={
                "exit_status": "Submitted",
                "submission": "Hello! How can I help you today?",
                "verification_status": "idle",
                "verification": {"status": "idle", "artifact_count": 0, "diff_count": 0, "gaps": []},
            },
        )
    )
    out = buf.getvalue()
    assert "artifacts" not in out
    assert "couldn't fully verify" not in out


def test_edit_tool_end_shows_diff_stat() -> None:
    buf, display = _display()
    display(
        Event(
            "tool_end",
            payload={
                "tool": "edit",
                "ok": True,
                "diff": "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1,2 @@\n-old\n+new\n+extra\n",
                "duration_ms": 400,
            },
        )
    )
    out = buf.getvalue()
    assert "edit" in out
    from tests.conftest import strip_ansi

    assert "+2,-1" in strip_ansi(out)


def test_parallel_tool_start_shows_batch_header() -> None:
    buf, display = _display()
    display(
        Event(
            "tool_start",
            payload={
                "tool": "read",
                "arguments": {"path": "src/a.py"},
                "parallel_batch": 3,
            },
        )
    )
    out = buf.getvalue()
    assert "parallel 3" in out
    assert "read" in out


def test_read_tool_end_shows_line_count_summary() -> None:
    buf, display = _display()
    display(
        Event(
            "tool_end",
            payload={
                "tool": "read",
                "ok": True,
                "output": "line one\nline two\nline three\n",
                "duration_ms": 12,
            },
        )
    )
    out = buf.getvalue()
    assert "3 lines" in out


def test_stream_coalescing_batches_answer_deltas() -> None:
    buf, display = _display()
    display(Event("stream_start", payload={}))
    display(Event("stream_delta", payload={"text": "Hello"}))
    display(Event("stream_delta", payload={"text": " world"}))
    display(Event("stream_end", payload={}))
    out = buf.getvalue()
    assert "Hello world" in out


def test_compact_event_updates_context_meter() -> None:
    buf, display = _display()
    display(
        Event(
            "compact",
            payload={"before": 42, "after": 12, "total_tokens": 24_000, "window": 128_000},
        )
    )
    assert display.state.tokens == 24_000
    assert display.state.window == 128_000
    out = buf.getvalue()
    assert "42 → 12" in out
    assert "ctx" in out.lower()


def test_context_event_updates_state() -> None:
    _, display = _display()
    display(Event("context", payload={"total_tokens": 50_000, "window": 100_000}))
    assert display.state.tokens == 50_000
    assert display.state.window == 100_000
    assert display.state.context_pct == 0.5


def test_failed_verification_still_warns() -> None:
    buf, display = _display()
    display(
        Event(
            "artifact",
            payload={"status": "failed", "artifact_count": 1, "diff_count": 0, "gaps": ["pytest failed"], "artifacts": []},
        )
    )
    display(
        Event(
            "agent_end",
            payload={
                "exit_status": "Submitted",
                "submission": "done",
                "verification_status": "failed",
                "verification": {"status": "failed", "artifact_count": 1, "gaps": ["pytest failed"]},
            },
        )
    )
    out = buf.getvalue()
    assert "artifacts  failed" in out
    assert "couldn't fully verify" in out
