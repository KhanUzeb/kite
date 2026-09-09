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


def test_approval_enter_empty_allows_once(monkeypatch) -> None:
    """Empty Enter during approval allows once (not deny)."""
    from kite.ui.complete import _prompt_once

    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    session = MagicMock()
    session.prompt.return_value = "a"
    session.default_buffer.text = ""
    state = SessionUiState(awaiting_approval="bash")
    result = _prompt_once(session, state, busy=True, action_slot={"kind": "approval"})
    assert result.kind == "approval"
    assert result.text == "allow"


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
    assert "tok/s" in busy_html
    assert "›" in format_running_status(busy)

    approval = SessionUiState(awaiting_approval="bash", awaiting_approval_mandatory=True)
    approval_html = str(_toolbar_html(approval))
    assert "[a]/Enter once" in approval_html
    assert "Enter queue" not in approval_html

    idle_html = str(_toolbar_html(SessionUiState(busy=False)))
    assert "Esc stop" not in idle_html
