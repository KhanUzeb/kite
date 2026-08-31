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
    display(Event("warning", payload={"message": "MCP filesystem failed"}))
    out = buf.getvalue()
    assert "MCP filesystem failed" in out


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
