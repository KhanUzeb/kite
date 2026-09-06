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


def test_slash_stop_idle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="test"),
    )
    from kite.ui.repl import ChatSession

    chat = ChatSession(cwd=str(tmp_path))
    chat._slash_stop("")
    assert chat._session_id is None


def test_classify_busy_line() -> None:
    from kite.ui.complete import classify_busy_line

    assert classify_busy_line("/stop").kind == "stop"
    assert classify_busy_line("/quit").kind == "eof"
    assert classify_busy_line("/steer use grep").kind == "steer"
    assert classify_busy_line("/steer use grep").text == "use grep"
    assert classify_busy_line("/tasks").kind == "slash"
    assert classify_busy_line("follow up").kind == "text"


def test_busy_placeholder_is_quiet(monkeypatch) -> None:
    monkeypatch.setattr(
        "prompt_toolkit.patch_stdout.patch_stdout",
        lambda raw=False: nullcontext(),
    )
    captured: dict[str, object] = {}
    session = MagicMock()

    def _prompt(*_a, **kwargs):
        captured["placeholder"] = kwargs.get("placeholder")
        raise EOFError()

    session.prompt.side_effect = _prompt
    read_repl_line(
        session=session,
        state=SessionUiState(busy=True),
        fallback=lambda: None,
        busy=True,
    )
    ph = str(captured.get("placeholder") or "")
    assert "Esc" not in ph
    assert "Ctrl+G" not in ph
    assert "type to queue" not in ph.lower()
    assert "follow-up" in ph.lower()


def test_busy_toolbar_has_steer_and_budget() -> None:
    from kite.ui.complete import _toolbar_html

    state = SessionUiState(busy=True, queued=2, budget_limit=5.0)
    html = str(_toolbar_html(state))
    assert "Esc stop" in html
    assert "Enter queue" in html
    assert "Ctrl+G steer" in html
    assert "queued 2" in html
    assert "/tasks" in html
    assert "budget ≤$5.00" in html


def test_approval_toolbar_shows_decision_keys_not_queue() -> None:
    from kite.ui.complete import _toolbar_html

    state = SessionUiState(busy=True, awaiting_approval="bash", awaiting_approval_mandatory=True)
    html = str(_toolbar_html(state))
    assert "[a] once" in html
    assert "[n] deny" in html
    assert "[q] stop" in html
    assert "mandatory" in html
    assert "Enter queue" not in html
    assert "Ctrl+G steer" not in html


def test_approval_toolbar_optional_session_keys() -> None:
    from kite.ui.complete import _toolbar_html

    html = str(_toolbar_html(SessionUiState(awaiting_approval="write", awaiting_approval_mandatory=False)))
    assert "[s] session" in html
    assert "[p] always" in html


def test_at_attach_prefix_skips_email() -> None:
    from kite.ui.complete import _at_attach_prefix

    assert _at_attach_prefix("mail user@example.com") is None
    assert _at_attach_prefix("@src/") == ("src/", -4)
    assert _at_attach_prefix("see @docs/") == ("docs/", -5)


def test_idle_toolbar_omits_steer_hints() -> None:
    from kite.ui.complete import _toolbar_html

    html = str(_toolbar_html(SessionUiState(busy=False, queued=0)))
    assert "Esc stop" not in html
    assert "Ctrl+G steer" not in html
    assert "budget" not in html


def test_busy_toolbar_shows_running_line() -> None:
    from kite.ui.complete import _toolbar_html

    state = SessionUiState(
        busy=True,
        running_label="Get-ChildItem -Path C:\\",
        running_since="15:41:50",
    )
    html = str(_toolbar_html(state))
    assert "15:41:50" in html
    assert "running" in html
    assert "Get-ChildItem" in html


def test_tasks_builtin_registered() -> None:
    from kite.ui.commands import parse_slash

    assert parse_slash("/tasks").command == "tasks"


def test_format_running_status() -> None:
    from kite.ui.status import active_task_count, format_metrics_tail, format_running_status

    state = SessionUiState(busy=True, queued=2, running_label="pytest -q", running_since="12:00:00")
    assert "running" in format_running_status(state)
    assert active_task_count(state) == 3
    metrics = format_metrics_tail(state)
    assert "tok/s" in metrics
    assert "$" in metrics


def test_note_stream_delta_updates_tps() -> None:
    import time

    state = SessionUiState()
    state.note_stream_delta("hello world " * 20)
    time.sleep(0.02)
    state.note_stream_delta("more tokens here")
    assert state.tps > 0


def test_busy_toolbar_includes_metrics() -> None:
    from kite.ui.complete import _toolbar_html

    state = SessionUiState(busy=True, window=128_000, tokens=32_000, cache_hit_ratio=0.2, tps=42.0)
    html = str(_toolbar_html(state))
    assert "tok/s" in html
    assert "cache" in html
    assert "ctx" in html
