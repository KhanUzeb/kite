"""Busy composer and approval polling — no hang on pending approval."""

from __future__ import annotations

from unittest.mock import MagicMock

from kite.application.policy import ApprovalCoordinator
from kite.ui.state import SessionUiState


def test_poll_pending_approval_sets_footer_state() -> None:
    from kite.ui.repl import ChatSession

    repl = ChatSession(cwd=".", provider="fake", model="fake")
    repl._approval_coordinator = ApprovalCoordinator(interactive=True)
    repl._approval_coordinator._pending = MagicMock(tool="bash", request_id="r1")  # noqa: SLF001
    repl._poll_pending_approval()
    assert repl.state.awaiting_approval == "bash"
    repl._approval_coordinator._pending = None  # noqa: SLF001
    repl._poll_pending_approval()
    assert repl.state.awaiting_approval == ""


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
    assert "tests not run" in out


def test_verification_status_updates_state() -> None:
    from io import StringIO

    from rich.console import Console

    from kite.agent.events import Event
    from kite.ui.render import RunDisplay
    from kite.ui.style import KITE_THEME

    state = SessionUiState()
    console = Console(file=StringIO(), width=80, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=state, quiet=False)
    display(Event("verification_status", payload={"status": "changed_unverified"}))
    assert state.verification_status == "changed_unverified"
    assert "verification" in state.flash


def test_spin_while_busy_updates_toolbar_not_stderr_spinner() -> None:
    """Pinned composer owns the bottom line — stderr WaitSpinner must not run."""
    from io import StringIO

    from rich.console import Console

    from kite.ui.render import RunDisplay
    from kite.ui.style import KITE_THEME

    state = SessionUiState(busy=True)
    console = Console(file=StringIO(), width=80, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=state, quiet=False)
    display._spin(True, "thinking")
    assert display._spinner_on is False
    assert state.running_label == "thinking"
    display._spin(True, "working  read")
    assert display._spinner_on is False
    assert state.running_label == "working  read"


def test_spin_while_busy_stops_existing_spinner() -> None:
    from io import StringIO
    from unittest.mock import MagicMock

    from rich.console import Console

    from kite.ui.render import RunDisplay
    from kite.ui.style import KITE_THEME

    state = SessionUiState(busy=True)
    console = Console(file=StringIO(), width=80, force_terminal=True, theme=KITE_THEME)
    display = RunDisplay(console, state=state, quiet=False)
    display._spinner = MagicMock()
    display._spinner_on = True
    display._spin(True, "thinking")
    display._spinner.stop.assert_called()
    assert display._spinner_on is False


def test_status_tail_with_awaiting_approval_does_not_crash() -> None:
    from kite.ui.status import format_status_tail

    state = SessionUiState(busy=True, awaiting_approval="bash", provider="groq", model="x")
    tail = format_status_tail(state)
    assert "approve bash" in tail
    assert "working" in tail
