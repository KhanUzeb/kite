"""RunDisplay event handling (no TTY)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState


def test_warning_event_prints_muted_line() -> None:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True)
    display = RunDisplay(console, state=SessionUiState(), quiet=False)
    display(Event("warning", payload={"message": "MCP filesystem failed"}))
    out = buf.getvalue()
    assert "MCP filesystem failed" in out
