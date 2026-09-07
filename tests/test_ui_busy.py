"""Busy composer and approval polling."""

from __future__ import annotations

from unittest.mock import MagicMock

from kite.application.policy import ApprovalCoordinator


def test_poll_pending_approval_sets_footer_state() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._approval_coordinator = ApprovalCoordinator(interactive=True)
    repl._approval_coordinator._pending = MagicMock(tool="bash", request_id="r1", mandatory=True)  # noqa: SLF001
    repl._poll_pending_approval()
    assert repl.state.awaiting_approval == "bash"
    assert repl.state.awaiting_approval_mandatory is True


def test_resolve_skips_rich_prompt_while_composer_running() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._approval_coordinator = ApprovalCoordinator(interactive=True)
    repl._approval_coordinator._pending = MagicMock(  # noqa: SLF001
        tool="bash",
        request_id="r1",
        arguments={},
        diff="",
        reason="test",
        mandatory=True,
    )
    repl._prompt = MagicMock(app=MagicMock(is_running=True))
    repl._resolve_pending_approval()
    assert repl.state.awaiting_approval == "bash"


def test_submit_blocked_renders_warning() -> None:
    from io import StringIO

    from rich.console import Console

    from kite.agent.events import Event
    from kite.ui.render import RunDisplay
    from kite.ui.style import KITE_THEME
    from tests.conftest import strip_ansi

    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, quiet=False)
    display(Event("submit_blocked", payload={"reason": "tests not run"}))
    out = strip_ansi(buf.getvalue())
    assert "submit blocked" in out.lower()


def test_spin_while_busy_updates_toolbar_not_stderr_spinner() -> None:
    from io import StringIO

    from rich.console import Console

    from kite.ui.render import RunDisplay
    from kite.ui.state import SessionUiState
    from kite.ui.style import KITE_THEME

    state = SessionUiState(busy=True)
    console = Console(file=StringIO(), width=80, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=state, quiet=False)
    display._spin(True, "thinking")
    assert display._spinner_on is False
    assert state.running_label == "thinking"
