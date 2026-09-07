"""UI event queue and throttled toolbar refresh."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from kite.agent.events import Event
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME


def test_touch_throttled_during_streaming() -> None:
    state = SessionUiState()
    calls: list[int] = []

    def _refresh() -> None:
        calls.append(1)

    state._refresh = _refresh
    state.touch()
    state.touch()
    state.touch()
    assert len(calls) == 1
    assert state._touch_pending
    state.flush_pending_touch()
    assert len(calls) == 2
    assert not state._touch_pending


def test_ui_event_handler_queues_while_busy() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._busy = True
    event = Event("turn_start", payload={})
    repl._ui_event_handler(event)
    assert repl._ui_queue.qsize() == 1


def test_drain_ui_queue_renders_on_main_thread() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._busy = True
    repl._ui_queue.put(Event("turn_start", payload={}))
    repl._drain_ui_queue()
    assert repl._ui_queue.qsize() == 0


def test_coalesced_stream_updates_tps_once() -> None:
    state = SessionUiState()
    console = Console(file=StringIO(), width=80, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=state, quiet=False)
    display._coalesced_stream("answer", "x" * 300)
    assert state.stream_chars >= 300
    display._coalesced_stream("answer", "y" * 300)
    assert state.stream_chars >= 600
