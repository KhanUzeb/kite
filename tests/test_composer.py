"""Composer stop / steer / queue — keep the same session after interrupt."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

from kite.ui.complete import read_repl_line
from kite.ui.state import SessionUiState


def test_idle_ctrl_c_does_not_quit(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = ""
    result = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None)
    assert result.kind == "empty"


def test_busy_ctrl_c_with_text_steers(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = "use grep not find"
    result = read_repl_line(
        session=session,
        state=SessionUiState(),
        fallback=lambda: None,
        busy=True,
    )
    assert result.kind == "steer"
    assert result.text == "use grep not find"


def test_busy_ctrl_c_empty_stops(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = ""
    result = read_repl_line(
        session=session,
        state=SessionUiState(),
        fallback=lambda: None,
        busy=True,
    )
    assert result.kind == "stop"


def test_eof_quits(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.side_effect = EOFError()
    result = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None)
    assert result.kind == "eof"


def test_queue_counts_and_drain() -> None:
    from kite.agent.queue import RunMessageQueue

    q = RunMessageQueue()
    q.enqueue("later")
    q.steer("now")
    assert q.counts() == (1, 1)
    assert q.peek_entry() == ("now", True)
    drained = q.drain_all()
    assert drained == [("now", True), ("later", False)]
    assert len(q) == 0


def test_compaction_start_end_render() -> None:
    from io import StringIO

    from rich.console import Console

    from kite.agent.events import Event
    from kite.ui.render import RunDisplay
    from kite.ui.state import SessionUiState
    from kite.ui.style import KITE_THEME
    from tests.conftest import strip_ansi

    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=True, theme=KITE_THEME)
    state = SessionUiState(busy=True)
    display = RunDisplay(console, state=state, quiet=False)
    display(Event("compaction_start", payload={"total_tokens": 90000, "window": 128000}))
    display(Event("compaction_end", payload={"compacted": True, "total_tokens": 40000, "window": 128000}))
    out = strip_ansi(buf.getvalue())
    assert "compacting context" in out
    assert state.compacting is False


def test_retry_running_status_counts_down() -> None:
    import time

    from kite.ui.state import SessionUiState
    from kite.ui.status import format_running_status

    state = SessionUiState(busy=True, retry_until=time.monotonic() + 3, retry_label="2/5")
    line = format_running_status(state)
    assert "retrying in" in line
    assert "2/5" in line


def test_queue_steer_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    from kite.ui.repl import ChatSession

    chat = ChatSession(cwd=str(tmp_path))
    chat._queue_message("later")
    chat._queue_steer("first")
    assert list(chat._inbox) == ["first", "later"]
    assert chat.state.queued == 2
    assert chat.state.queue_steer == 1
    assert chat.state.queue_follow == 1


def test_classify_busy_line() -> None:
    from kite.ui.complete import classify_busy_line

    assert classify_busy_line("/stop").kind == "stop"
    assert classify_busy_line("/quit").kind == "eof"
    assert classify_busy_line("/steer use grep").kind == "steer"
    assert classify_busy_line("/steer use grep").text == "use grep"
    assert classify_busy_line("/tasks").kind == "busy_slash"
    assert classify_busy_line("/model").kind == "slash"
    assert classify_busy_line("follow up").kind == "text"


def test_approval_choice_and_busy_slash() -> None:
    from kite.ui.complete import is_busy_safe_slash, parse_approval_choice

    assert is_busy_safe_slash("/tasks")
    assert is_busy_safe_slash("/HELP")
    assert is_busy_safe_slash("/approve auto")
    assert not is_busy_safe_slash("/compact")
    assert parse_approval_choice("a", mandatory=False) == "allow"
    assert parse_approval_choice("s", mandatory=True) is None
    assert parse_approval_choice("n", mandatory=True) == "deny"


def test_approval_wake_empty_does_not_deny(monkeypatch) -> None:
    """Composer wake exits empty while awaiting — must not auto-deny."""
    from kite.ui.complete import _prompt_once

    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.return_value = ""
    session.default_buffer.text = ""
    state = SessionUiState(awaiting_approval="bash", awaiting_approval_mandatory=False)
    result = _prompt_once(session, state, busy=True, action_slot={"kind": "submit"})
    assert result.kind == "empty"
    assert result.text == ""


def test_approval_enter_empty_allows_once() -> None:
    from prompt_toolkit.keys import Keys

    from kite.ui.complete import make_repl_key_bindings

    action_slot = {"kind": "submit"}
    bindings = make_repl_key_bindings(
        is_awaiting_approval=lambda: True,
        action_slot=action_slot,
    )
    enter = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.ControlM,))
        if binding.handler.__name__ == "_approval_enter"
    )
    event = MagicMock()
    event.current_buffer.text = ""

    enter.handler(event)

    assert action_slot == {"kind": "approval"}
    event.app.exit.assert_called_once_with(result="a")


def test_slash_completion_selection_is_separate_from_input() -> None:
    from prompt_toolkit.buffer import Buffer, CompletionState
    from prompt_toolkit.completion import Completion
    from prompt_toolkit.document import Document

    from kite.ui.complete import _move_slash_completion, _select_first_slash_completion

    buffer = Buffer()
    buffer.document = Document("/se")
    state = CompletionState(
        buffer.document,
        [
            Completion("security", start_position=-2),
            Completion("settings", start_position=-2),
        ],
    )
    buffer.complete_state = state

    _select_first_slash_completion(buffer)
    assert state.complete_index == 0
    assert buffer.text == "/se"

    _move_slash_completion(buffer, -1)
    assert state.complete_index == 1
    assert buffer.text == "/se"


def test_prompt_session_wires_automatic_slash_selection(monkeypatch) -> None:
    from types import SimpleNamespace

    from prompt_toolkit.completion import Completion

    import kite.ui.complete as complete

    class Hook:
        callback = None

        def __iadd__(self, callback):
            self.callback = callback
            return self

    completion = Completion("security", start_position=-2)
    state = SimpleNamespace(
        completions=[completion],
        complete_index=None,
        current_completion=None,
        go_to_index=lambda index: setattr(state, "complete_index", index),
    )
    buffer = SimpleNamespace(
        complete_state=state,
        document=SimpleNamespace(text_before_cursor="/se"),
        on_completions_changed=Hook(),
    )
    session = SimpleNamespace(default_buffer=buffer)
    monkeypatch.setattr(complete, "PromptSession", lambda **_: session)

    complete.make_prompt_session(complete.SlashCompleter(lambda: None))
    buffer.on_completions_changed.callback(None)

    assert state.complete_index == 0


def test_prompt_session_uses_bounded_composer_layout(kite_home) -> None:
    from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu

    import kite.ui.complete as complete

    session = complete.make_prompt_session(complete.SlashCompleter(lambda: None))
    windows = [
        window
        for window in session.layout.find_all_windows()
        if getattr(getattr(window, "content", None), "buffer", None)
        is session.default_buffer
    ]
    assert windows
    assert all(window.style == "class:composer" for window in windows)
    assert all(window.height.min == 1 and window.height.max == 1 for window in windows)

    main = session.layout.container.children[0].alternative_content
    body = main.content
    assert any(isinstance(child, (CompletionsMenu, MultiColumnCompletionsMenu)) for child in body.children)
    assert all(
        not isinstance(floating.content, (CompletionsMenu, MultiColumnCompletionsMenu))
        for floating in main.floats
    )
    column_menu = next(child for child in body.children if isinstance(child, CompletionsMenu))
    assert column_menu.content.right_margins == []

def test_exact_slash_completion_does_not_leave_empty_menu_selected() -> None:
    from prompt_toolkit.buffer import Buffer, CompletionState
    from prompt_toolkit.completion import Completion
    from prompt_toolkit.document import Document

    from kite.ui.complete import _select_first_slash_completion

    buffer = Buffer()
    buffer.document = Document("/security")
    state = CompletionState(
        buffer.document,
        [Completion("security", start_position=-8)],
    )
    buffer.complete_state = state

    _select_first_slash_completion(buffer)

    assert state.complete_index is None


def test_enter_applies_selected_slash_completion_before_submit() -> None:
    from types import SimpleNamespace

    from prompt_toolkit.completion import Completion
    from prompt_toolkit.keys import Keys

    from kite.ui.complete import make_repl_key_bindings

    completion = Completion("security", start_position=-2)
    state = SimpleNamespace(
        completions=[completion],
        complete_index=0,
        current_completion=completion,
    )
    applied: list[Completion] = []
    buffer = SimpleNamespace(
        complete_state=state,
        document=SimpleNamespace(text_before_cursor="/se"),
        text="/se",
        apply_completion=applied.append,
        validate_and_handle=MagicMock(),
    )
    bindings = make_repl_key_bindings()
    enter = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.ControlM,))
        if binding.handler.__name__ == "_submit"
    )

    enter.handler(SimpleNamespace(current_buffer=buffer))

    assert applied == [completion]
    assert buffer.complete_state is None
    buffer.validate_and_handle.assert_called_once_with()


def test_toolbar_busy_and_approval_states() -> None:
    from kite.ui.complete import _toolbar_html
    from kite.ui.status import format_running_status

    busy = SessionUiState(
        busy=True,
        queued=2,
        queue_steer=1,
        queue_follow=1,
        queue_head="fix the flaky test",
        queue_head_kind="steer",
        budget_limit=5.0,
        running_label="pytest -q",
        running_since="12:00:00",
        activity_preview="PASSED",
        window=128_000,
        tokens=32_000,
        cache_hit_ratio=0.2,
        tps=42.0,
    )
    busy_html = str(_toolbar_html(busy))
    assert "Esc/Ctrl+C stop" in busy_html
    assert "steer 1" in busy_html
    assert "follow-up 1" in busy_html
    assert "next steer: fix the flaky test" in busy_html
    assert "tok/s" not in busy_html
    assert "›" in format_running_status(busy)

    approval = SessionUiState(awaiting_approval="bash", awaiting_approval_mandatory=True)
    approval_html = str(_toolbar_html(approval))
    assert "[a] once" in approval_html
    assert "[Enter] once" not in approval_html
    assert "Enter queue" not in approval_html

    idle_html = str(_toolbar_html(SessionUiState(busy=False)))
    assert "Esc stop" not in idle_html
