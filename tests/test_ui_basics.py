"""Status line, spinner, composer keys, polish, event queue, busy routing."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.approval import render_approval_panel
from kite.ui.complete import (
    BusyComposerHandlers,
    ComposerResult,
    SlashCompleter,
    apply_busy_composer_result,
    make_repl_key_bindings,
)
from kite.ui.render import RunDisplay, render_status
from kite.ui.spinner import WaitSpinner, stop_all_spinners
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import cache_meter, context_meter, format_metrics_tail, format_status_tail
from kite.ui.style import KITE_THEME
from tests.conftest import strip_ansi


@pytest.fixture
def completer() -> SlashCompleter:
    return SlashCompleter(
        index_factory=lambda: MagicMock(specs={}, skills=[], plugins=[]),
        models_factory=lambda: [],
        providers_factory=lambda: [],
    )


# --- status ---


def test_context_meter_and_usage() -> None:
    state = SessionUiState(window=100_000)
    state.set_context_usage(total_tokens=25_000, window=100_000)
    meter = context_meter(state.context_pct)
    assert "25%" in meter
    assert context_meter(None) == ""


def test_format_status_tail_includes_cache_and_agents() -> None:
    state = SessionUiState(
        provider="groq",
        model="llama",
        tokens=4000,
        window=8000,
        cost=0.12,
        cache_hit_ratio=0.25,
        active_subagents=2,
    )
    tail = format_status_tail(state)
    metrics = format_metrics_tail(state)
    assert "cache" in metrics
    assert "agents 2" in tail
    assert "25%" in cache_meter(0.25)


def test_format_status_tail_plan_mode() -> None:
    state = SessionUiState(
        mode=AgentMode.PLAN,
        approval=ApprovalMode.READONLY,
        model="m",
        todos=[TodoItem(id="1", content="explore", status="completed"), TodoItem(id="2", content="ship")],
    )
    tail = format_status_tail(state)
    assert "plan" in tail
    assert "readonly" in tail.lower()
    rendered = render_status(state).plain
    assert "plan" in rendered


# --- spinner ---


def test_start_under_pytest_skips_daemon_thread() -> None:
    buf = StringIO()
    spinner = WaitSpinner(stream=buf, delay=0.01)
    spinner.start()
    assert spinner._thread is None
    spinner.kick("working")
    stop_all_spinners()
    assert spinner._thread is None


# --- composer keys ---


def test_repl_key_bindings_include_paste_copy_not_scroll_by_default(monkeypatch) -> None:
    monkeypatch.delenv("KITE_MOUSE", raising=False)
    bindings = make_repl_key_bindings()
    if bindings is None:
        pytest.skip("prompt_toolkit unavailable")
    keys: set[str] = set()
    for binding in bindings.bindings:
        keys.update(binding.keys)
    assert "c-v" in keys
    assert "escape" in keys
    assert "c-g" in keys
    assert "<scroll-up>" not in keys


# --- polish ---


def test_thinking_collapses_when_disabled() -> None:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=SessionUiState(thinking_expanded=False), quiet=False)
    display(Event("stream_start", payload={}))
    display(Event("stream_reasoning", payload={"text": "step one\nstep two\n"}))
    display(Event("stream_end", payload={}))
    out = strip_ansi(buf.getvalue())
    assert "2 lines" in out
    display.close()


def test_approval_panel_uses_left_bar_layout() -> None:
    panel = render_approval_panel("bash", {"command": "pytest -q", "cwd": "src"})
    out = strip_ansi(panel.plain)
    assert "approve" in out
    assert "[a]" in out


def test_approval_event_is_silent() -> None:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=SessionUiState(), quiet=False)
    display(Event("approval", payload={"tool": "bash"}))
    assert strip_ansi(buf.getvalue()) == ""


# --- event queue ---


def test_ui_event_handler_queues_while_busy() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._busy = True
    repl._prompt = MagicMock(app=MagicMock(is_running=True))
    repl._ui_event_handler(Event("turn_start", payload={}))
    assert repl._ui_queue.qsize() == 1
    repl._prompt.app.exit.assert_not_called()


def test_drain_ui_queue_renders_on_main_thread() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._busy = True
    repl._ui_queue.put(Event("turn_start", payload={}))
    repl._drain_ui_queue()
    assert repl._ui_queue.qsize() == 0


# --- busy composer ---


def test_apply_busy_queues_text() -> None:
    queued: list[str] = []
    handlers = BusyComposerHandlers(
        on_queue=queued.append,
        on_stop=MagicMock(),
        on_steer=MagicMock(),
        on_slash_while_busy=MagicMock(),
    )
    assert apply_busy_composer_result(ComposerResult("text", "follow up"), handlers) is False
    assert queued == ["follow up"]


def test_apply_busy_eof_stops() -> None:
    stopped = {"x": False}
    handlers = BusyComposerHandlers(
        on_queue=MagicMock(),
        on_stop=lambda: stopped.update(x=True),
        on_steer=MagicMock(),
        on_slash_while_busy=MagicMock(),
    )
    assert apply_busy_composer_result(ComposerResult("text", "/quit"), handlers) is True
    assert stopped["x"] is True


def test_apply_busy_empty_uses_on_empty() -> None:
    calls = {"empty": 0, "slash": 0}
    handlers = BusyComposerHandlers(
        on_queue=MagicMock(),
        on_stop=MagicMock(),
        on_steer=MagicMock(),
        on_slash_while_busy=lambda: calls.update(slash=calls["slash"] + 1),
        on_empty=lambda: calls.update(empty=calls["empty"] + 1),
    )
    assert apply_busy_composer_result(ComposerResult("empty"), handlers) is False
    assert calls["empty"] == 1
    assert calls["slash"] == 0


def test_note_stream_delta_skips_touch_while_busy() -> None:
    state = SessionUiState(busy=True)
    state._refresh = MagicMock()  # noqa: SLF001
    state.note_stream_delta("hello world")
    state._refresh.assert_not_called()  # noqa: SLF001
