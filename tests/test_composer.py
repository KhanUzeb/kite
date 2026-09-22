"""Composer stop / steer / queue — keep the same session after interrupt."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

from kite.ui.complete import read_repl_line
from kite.ui.state import SessionUiState


def test_composer_interrupt_kinds_queue_and_eof(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = ""
    result = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None)
    assert result.kind == "empty"

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

    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = ""
    result = read_repl_line(
        session=session,
        state=SessionUiState(),
        fallback=lambda: None,
        busy=True,
    )
    assert result.kind == "stop"

    session.prompt.side_effect = EOFError()
    result = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None)
    assert result.kind == "eof"

    from kite.agent.queue import RunMessageQueue

    q = RunMessageQueue()
    q.enqueue("later")
    q.steer("now")
    assert q.counts() == (1, 1)
    assert q.peek_entry() == ("now", True)
    drained = q.drain_all()
    assert drained == [("now", True), ("later", False)]
    assert len(q) == 0


def test_busy_enter_steer_queue_classification(tmp_path, monkeypatch) -> None:
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

    from unittest.mock import MagicMock as _MagicMock

    from kite.ui.complete import _prompt_once, busy_enter_queues_followup
    from kite.ui.state import SessionUiState as _State

    monkeypatch.delenv("KITE_BUSY_ENTER", raising=False)
    assert not busy_enter_queues_followup()
    monkeypatch.setattr("prompt_toolkit.patch_stdout.patch_stdout", lambda raw=False: nullcontext())
    session = _MagicMock()
    session.prompt.return_value = "redirect me"
    slot = {"kind": "submit"}
    result = _prompt_once(session, _State(busy=True), busy=True, action_slot=slot)
    assert result.kind == "steer" and result.text == "redirect me"
    monkeypatch.setenv("KITE_BUSY_ENTER", "queue")
    assert busy_enter_queues_followup()
    slot = {"kind": "submit"}
    result = _prompt_once(session, _State(busy=True), busy=True, action_slot=slot)
    assert result.kind == "text" and result.text == "redirect me"

    from kite.ui.complete import classify_busy_line

    assert classify_busy_line("/stop").kind == "stop"
    assert classify_busy_line("/quit").kind == "eof"
    assert classify_busy_line("/q").kind == "eof"
    assert classify_busy_line("/exit").kind == "eof"
    assert classify_busy_line("/steer use grep").kind == "steer"
    assert classify_busy_line("/steer use grep").text == "use grep"
    assert classify_busy_line("/tasks").kind == "busy_slash"
    assert classify_busy_line("/model").kind == "slash"
    assert classify_busy_line("follow up").kind == "text"

    from kite.ui.complete import is_busy_safe_slash, parse_approval_choice

    assert is_busy_safe_slash("/tasks")
    assert is_busy_safe_slash("/HELP")
    assert is_busy_safe_slash("/approve auto")
    assert not is_busy_safe_slash("/compact")
    assert parse_approval_choice("a", mandatory=False) == "allow"
    assert parse_approval_choice("s", mandatory=True) is None
    assert parse_approval_choice("n", mandatory=True) == "deny"


def test_approval_composer_keys(monkeypatch) -> None:
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


def test_slash_completion_wiring() -> None:
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

    from prompt_toolkit.completion import CompleteEvent

    import kite.ui.complete as complete
    from kite.cli.slash import CommandIndex

    completer = complete.SlashCompleter(lambda: CommandIndex.load("."))
    exit_rows = list(completer.get_completions(Document("/exi"), CompleteEvent()))
    assert [row.text for row in exit_rows] == ["exit"]
    assert "Leave the REPL" in str(exit_rows[0].display_meta)
    assert "exit" in str(exit_rows[0].display)
    prefix_rows = list(completer.get_completions(Document("/ex"), CompleteEvent()))
    assert "exit" in [row.text for row in prefix_rows]
    all_rows = list(completer.get_completions(Document("/"), CompleteEvent()))
    names = [row.text for row in all_rows]
    assert "quit" in names and "exit" in names


def test_composer_layout_multiline_and_newlines(kite_home, monkeypatch) -> None:
    from types import SimpleNamespace

    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
    from prompt_toolkit.output import DummyOutput

    import kite.ui.complete as complete

    state = SessionUiState()
    # DummyOutput keeps the test hermetic: real console outputs (Win32Output)
    # raise NoConsoleScreenBufferError on headless CI runners.
    session = complete.make_prompt_session(
        complete.SlashCompleter(lambda: None), state=state, output=DummyOutput()
    )
    windows = [
        window
        for window in session.layout.find_all_windows()
        if getattr(getattr(window, "content", None), "buffer", None)
        is session.default_buffer
    ]
    assert windows
    assert all(window.style == "class:composer" for window in windows)
    # Big-prompt fix: the input row grows (wrap + internal scroll) instead of
    # locking to one visible line and hiding the tail.
    assert 6 <= complete._COMPOSER_MAX_LINES <= 8
    assert all(window.height.min == 1 and window.height.max == complete._COMPOSER_MAX_LINES for window in windows)
    assert all(window.height.max > 1 for window in windows)
    assert all(window.wrap_lines() for window in windows)
    assert all(window.allow_scroll_beyond_bottom() for window in windows)

    main = session.layout.container.children[0].alternative_content
    body = main.content
    activity = next(
        child
        for child in body.children
        if isinstance(child, ConditionalContainer)
        and isinstance(getattr(child, "content", None), HSplit)
        and any(
            getattr(grandchild, "style", None) == "class:activity"
            for grandchild in child.content.children
        )
    )
    composer = next(child for child in body.children if isinstance(child, HSplit) and len(child.children) == 3)
    assert not activity.filter()
    state.busy = True
    assert activity.filter()
    assert body.children.index(activity) < body.children.index(composer)
    # Activity sits between two unpainted spacer rows: a gap above it from the
    # transcript and a gap below it before the composer box.
    spacer_top, activity_line, spacer_bottom = activity.content.children
    assert activity_line.style == "class:activity"
    assert spacer_top.style not in {"class:composer", "class:activity"}
    assert spacer_bottom.style not in {"class:composer", "class:activity"}
    assert all(isinstance(row, Window) for row in (spacer_top, activity_line, spacer_bottom))
    assert composer.height.min == 3 and composer.height.max == complete._COMPOSER_MAX_HEIGHT
    assert composer.height.max == complete._COMPOSER_MAX_LINES + 2
    assert 9 <= complete._COMPOSER_MAX_HEIGHT <= 10
    assert all(
        isinstance(child, Window) and child.style == "class:composer"
        for child in (composer.children[0], composer.children[2])
    )
    assert composer.children[0].char == " " and composer.children[2].char == " "

    menu_index = next(
        index
        for index, child in enumerate(body.children)
        if isinstance(child, (CompletionsMenu, MultiColumnCompletionsMenu))
    )
    assert body.children.index(composer) < menu_index
    assert all(
        not isinstance(floating.content, (CompletionsMenu, MultiColumnCompletionsMenu))
        for floating in main.floats
    )
    column_menu = next(child for child in body.children if isinstance(child, CompletionsMenu))
    assert column_menu.content.right_margins == []

    # The session must not force single-line mode — long prompts clip there.
    real_session_cls = complete.PromptSession
    seen: dict = {}

    def _recording_session(**kwargs):
        seen.update(kwargs)
        return real_session_cls(**kwargs)

    monkeypatch.setattr(complete, "PromptSession", _recording_session)
    multiline_session = complete.make_prompt_session(
        complete.SlashCompleter(lambda: None),
        state=SessionUiState(),
        output=DummyOutput(),
    )
    assert seen.get("multiline") is True
    assert multiline_session is not None

    prompt_seen: dict = {}
    multiline_session.prompt = lambda *a, **k: (prompt_seen.update(k) or "hello")  # type: ignore[method-assign]
    result = complete._prompt_once(
        multiline_session, SessionUiState(), busy=False, action_slot={"kind": "submit"}
    )
    assert prompt_seen.get("multiline") is True
    assert result.kind == "text" and result.text == "hello"

    # Ctrl+J and Alt+Enter insert newlines without submitting.
    bindings = complete.make_repl_key_bindings()
    inserted: list[str] = []
    buffer = SimpleNamespace(
        insert_text=inserted.append,
        validate_and_handle=MagicMock(),
    )
    event = SimpleNamespace(current_buffer=buffer)
    ctrl_j = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.ControlJ,))
        if binding.handler.__name__ == "_newline"
    )
    ctrl_j.handler(event)
    alt_enter = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.Escape, Keys.ControlM))
        if binding.handler.__name__ == "_newline"
    )
    alt_enter.handler(event)
    assert inserted == ["\n", "\n"]
    buffer.validate_and_handle.assert_not_called()


def test_slash_completion_submit_flow() -> None:
    from types import SimpleNamespace

    from prompt_toolkit.buffer import Buffer, CompletionState
    from prompt_toolkit.completion import Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.keys import Keys

    from kite.ui.complete import _select_first_slash_completion, make_repl_key_bindings

    buffer = Buffer()
    buffer.document = Document("/security")
    state = CompletionState(
        buffer.document,
        [Completion("security", start_position=-8)],
    )
    buffer.complete_state = state
    _select_first_slash_completion(buffer)
    assert state.complete_index is None

    completion = Completion("security", start_position=-2)
    menu_state = SimpleNamespace(
        completions=[completion],
        complete_index=0,
        current_completion=completion,
    )
    applied: list[Completion] = []
    submit_buffer = SimpleNamespace(
        complete_state=menu_state,
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
    enter.handler(SimpleNamespace(current_buffer=submit_buffer))
    assert applied == [completion]
    assert submit_buffer.complete_state is None
    submit_buffer.validate_and_handle.assert_called_once_with()


def test_toolbar_busy_approval_and_hints(monkeypatch) -> None:
    import time

    from kite.ui.complete import _activity_html, _toolbar_busy_bits, _toolbar_html
    from kite.ui.state import SessionUiState as _State
    from kite.ui.status import format_running_status

    retry_state = SessionUiState(busy=True, retry_until=time.monotonic() + 3, retry_label="2/5")
    line = format_running_status(retry_state)
    assert "retrying in" in line
    assert "2/5" in line

    busy = _State(
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
    activity_html = str(_activity_html(busy))
    assert "Esc/Ctrl+C stop" in busy_html
    assert "Enter steer" in busy_html
    assert "steer 1" in busy_html
    assert "follow-up 1" in busy_html
    assert "next steer: fix the flaky test" in busy_html
    assert "pytest -q" not in busy_html
    assert "pytest -q" in activity_html
    assert "tok/s" not in busy_html
    assert "›" in format_running_status(busy)

    approval = _State(awaiting_approval="bash", awaiting_approval_mandatory=True)
    approval_html = str(_toolbar_html(approval))
    assert "[a] once" in approval_html
    assert "[Enter] once" not in approval_html
    assert "Enter queue" not in approval_html

    idle_html = str(_toolbar_html(_State(busy=False)))
    assert "Esc stop" not in idle_html

    monkeypatch.delenv("KITE_BUSY_ENTER", raising=False)
    default_bits = _toolbar_busy_bits(_State(busy=True))
    assert "Enter steer" in default_bits
    # No duplicate explicit steer hint when Enter already steers.
    assert "Ctrl+G steer" not in default_bits
    monkeypatch.setenv("KITE_BUSY_ENTER", "queue")
    legacy_bits = _toolbar_busy_bits(_State(busy=True))
    assert "Enter queue" in legacy_bits
    assert "Ctrl+G steer" in legacy_bits


def test_busy_steer_keeps_composer_alive() -> None:
    """Steering must not stop/leave the busy composer — it interrupts the
    turn so the agent continues, while the composer stays pinned."""
    from kite.ui.complete import (
        BusyComposerHandlers,
        ComposerResult,
        dispatch_classified_busy,
    )

    calls: list[str] = []

    def _on_steer(text: str) -> None:
        calls.append(f"steer:{text}")

    def _on_stop() -> None:
        calls.append("stop")

    handlers = BusyComposerHandlers(
        on_queue=lambda t: calls.append(f"queue:{t}"),
        on_stop=_on_stop,
        on_steer=_on_steer,
        on_slash_while_busy=lambda: calls.append("slash-busy"),
    )
    # Steer queues + interrupts but keeps the pinned composer (returns False).
    assert dispatch_classified_busy(ComposerResult("steer", "use grep"), handlers) is False
    assert calls == ["steer:use grep"]
    # Explicit stop still leaves the composer loop.
    assert dispatch_classified_busy(ComposerResult("stop"), handlers) is True
    assert calls[-1] == "stop"
    # Queue never stops the loop either.
    assert dispatch_classified_busy(ComposerResult("text", "later"), handlers) is False
    assert calls[-1] == "queue:later"


def test_fold_long_paste_collapse_expand_and_bindings() -> None:
    from types import SimpleNamespace

    from prompt_toolkit.keys import Keys

    from kite.ui.complete import (
        _paste_fold_changed,
        fold_buffer,
        fold_long_text,
        is_folded,
        make_repl_key_bindings,
        unfold_buffer,
    )

    assert fold_long_text("short\ntwo lines") is None
    assert fold_long_text("\n".join(f"line {i}" for i in range(9))) is None
    text = "\n".join(f"line {i}" for i in range(12))
    folded, hidden = fold_long_text(text)  # type: ignore[misc]
    assert hidden == 9
    assert folded.startswith("line 0\nline 1\nline 2\n")
    assert "+9 lines" in folded

    buf = SimpleNamespace(text="", cursor_position=0)
    buf._kite_fold = {"folded": False, "full": "", "guard": False, "lines": 0}
    # Small typing never folds.
    buf.text = "hello\nworld"
    _paste_fold_changed(buf)
    assert not is_folded(buf)
    # A sudden long paste folds to head + placeholder.
    buf.text = "\n".join(f"line {i}" for i in range(15))
    _paste_fold_changed(buf)
    assert is_folded(buf)
    assert buf.text.startswith("line 0\nline 1\nline 2\n")
    assert "+12 lines" in buf.text
    # Full text is stashed, never lost.
    assert buf._kite_fold["full"].split("\n") == [f"line {i}" for i in range(15)]
    # Any interaction expands back to the full text.
    assert unfold_buffer(buf) is True
    assert buf.text.split("\n") == [f"line {i}" for i in range(15)]
    assert not is_folded(buf)
    assert fold_buffer(SimpleNamespace(text="tiny")) is False

    bindings = make_repl_key_bindings()
    fold_toggle = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.F9,))
        if binding.handler.__name__ == "_fold_toggle"
    )
    expand = next(
        binding
        for binding in bindings.get_bindings_for_keys((Keys.Any,))
        if binding.handler.__name__ == "_fold_expand"
    )
    key_buf = SimpleNamespace(text="\n".join(f"line {i}" for i in range(12)), cursor_position=0)
    event = SimpleNamespace(current_buffer=key_buf)
    fold_toggle.handler(event)
    assert is_folded(key_buf)
    # Placeholder is never what gets submitted — expansion restores first.
    expand.handler(event)
    assert not is_folded(key_buf)
    assert key_buf.text.split("\n") == [f"line {i}" for i in range(12)]


def test_plan_build_slash_text_runs_task(tmp_path, monkeypatch) -> None:
    """`/plan <text>` and `/build <text>` act immediately; bare forms report state."""
    from unittest.mock import MagicMock

    from kite.agent.mode import AgentMode
    from kite.ui.repl import ChatSession

    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    chat = ChatSession(cwd=str(tmp_path))
    ran: list[str] = []
    chat._run_task = lambda task: ran.append(task)  # type: ignore[method-assign]
    chat.display.print_user_turn = lambda text: None  # type: ignore[method-assign]

    chat.state.todos = [{"status": "pending", "content": "survey"}]
    chat._slash_plan("")
    assert ran == [] and chat.state.mode is AgentMode.PLAN
    chat._slash_plan("survey auth")
    assert ran == ["survey auth"]

    ran.clear()
    chat._slash_build("")
    assert ran == [] and chat.state.mode is AgentMode.BUILD
    chat._slash_build("fix it")
    assert ran == ["fix it"]


def test_reasoning_support_redetects_on_model_switch(tmp_path, monkeypatch) -> None:
    """Thinking levels must follow the current model, never a stale cache."""
    from unittest.mock import MagicMock

    import kite.models.reasoning as reasoning
    from kite.ui.repl import ChatSession

    calls: list[tuple[str, str]] = []

    def _fake_detect(provider: str, model: str, **_kwargs):
        calls.append((provider, model))
        return MagicMock(supported=True, model=model)

    monkeypatch.setattr(reasoning, "detect_reasoning", _fake_detect)
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    chat = ChatSession(cwd=str(tmp_path))
    chat._model_resolved = True
    chat.provider, chat.model = "groq", "model-a"
    assert chat._reasoning_info().model == "model-a"
    # Switch models with no explicit invalidation — levels must still refresh.
    chat.provider, chat.model = "groq", "model-b"
    assert chat._reasoning_info().model == "model-b"
    assert [model for _, model in calls] == ["model-a", "model-b"]


def test_queue_steer_falls_back_to_inbox_and_interrupts(tmp_path, monkeypatch) -> None:
    """A steer typed mid-turn must never be dropped when harness inject fails."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    from kite.ui.repl import ChatSession

    chat = ChatSession(cwd=str(tmp_path))
    harness = MagicMock()
    harness.inject_user_message.return_value = False
    chat._harness = harness
    chat._queue_steer("use grep not find")
    assert list(chat._inbox) == ["use grep not find"]
    harness.request_interrupt.assert_called_once()

    harness2 = MagicMock()
    harness2.inject_user_message.return_value = False
    chat._harness = harness2
    chat._queue_message("later")
    assert list(chat._inbox) == ["use grep not find", "later"]
