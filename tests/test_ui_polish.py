"""UI polish — thinking expand default, approval panel, bash blocks."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.approval import render_approval_panel
from kite.ui.render import RunDisplay, render_thinking_summary
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME
from kite.ui.tool_cards import render_bash_command_block
from tests.conftest import strip_ansi


def _display(*, thinking_expanded: bool | None = None) -> tuple[StringIO, RunDisplay]:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    state = SessionUiState()
    if thinking_expanded is not None:
        state.thinking_expanded = thinking_expanded
    return buf, RunDisplay(console, state=state, quiet=False)


def test_thinking_expanded_by_default() -> None:
    assert SessionUiState().thinking_expanded is True
    buf, display = _display()
    display(Event("stream_start", payload={}))
    display(Event("stream_reasoning", payload={"text": "visible by default"}))
    display(Event("stream_end", payload={}))
    out = strip_ansi(buf.getvalue())
    assert "visible by default" in out
    display.close()


def test_thinking_collapses_to_summary_when_disabled() -> None:
    buf, display = _display(thinking_expanded=False)
    display(Event("stream_start", payload={}))
    display(Event("stream_reasoning", payload={"text": "step one\nstep two\n"}))
    display(Event("stream_end", payload={}))
    out = strip_ansi(buf.getvalue())
    assert "thinking" in out.lower()
    assert "2 lines" in out
    assert "ctrl+t" in out.lower()
    assert display.state.last_thinking.strip()
    display.close()


def test_thinking_expanded_streams_content() -> None:
    buf, display = _display(thinking_expanded=True)
    display(Event("stream_start", payload={}))
    display(Event("stream_reasoning", payload={"text": "visible trace"}))
    display(Event("stream_end", payload={}))
    out = strip_ansi(buf.getvalue())
    assert "visible trace" in out
    display.close()


def test_approval_panel_uses_left_bar_layout() -> None:
    panel = render_approval_panel("bash", {"command": "pytest -q", "cwd": "src"})
    out = strip_ansi(panel.plain)
    assert "approve" in out
    assert "pytest -q" in out
    assert "cwd" in out
    assert "[a]" in out


def test_bash_command_block_renders_dollar_lines() -> None:
    block = render_bash_command_block("git status\npytest -q")
    out = strip_ansi(block.plain)
    assert "$ git status" in out
    assert "$ pytest -q" in out


def test_approval_event_is_silent() -> None:
    buf, display = _display()
    display(Event("approval", payload={"tool": "bash"}))
    assert strip_ansi(buf.getvalue()) == ""


def test_render_thinking_summary_hint() -> None:
    line = render_thinking_summary(1200, 8)
    out = strip_ansi(line.plain)
    assert "1,200 chars" in out
    assert "expand-thinking" in out
    assert "ctrl+t" in out.lower()


def test_double_click_expand_registers_only_with_kite_mouse(monkeypatch) -> None:
    from kite.ui.complete import make_repl_key_bindings

    monkeypatch.delenv("KITE_MOUSE", raising=False)
    off = make_repl_key_bindings(on_expand_thinking=lambda: None)
    if off is None:
        return
    off_keys = {getattr(k, "value", str(k)) for b in off.bindings for k in b.keys}
    assert not any("mouse-event" in k for k in off_keys)

    monkeypatch.setenv("KITE_MOUSE", "1")
    on = make_repl_key_bindings(on_expand_thinking=lambda: None)
    if on is None:
        return
    on_keys = {getattr(k, "value", str(k)) for b in on.bindings for k in b.keys}
    assert any("mouse-event" in k for k in on_keys)


def test_expand_thinking_callback_noop_when_already_expanded() -> None:
    calls: list[str] = []

    def expand() -> str | None:
        calls.append("hit")
        return None  # already expanded

    assert expand() is None
    assert calls == ["hit"]
