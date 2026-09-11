"""Textual TUI — Pi/Tau-style full-screen coding agent interface."""

from __future__ import annotations

import os
import sys
import threading
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from kite.agent.events import Event
from kite.ui.textual.display import TextualRunDisplay
from kite.ui.textual.messages import AgentEventMessage, StatusFlashMessage

if TYPE_CHECKING:
    from kite.ui.repl import ChatSession

KITE_CSS = """
Screen {
    layout: vertical;
}

#transcript {
    height: 1fr;
    border: solid $primary;
    padding: 0 1;
}

#status-line {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#composer {
    height: 3;
    border: tall $accent;
}

#flash {
    height: 1;
    color: $warning;
    padding: 0 1;
}

.approval-dialog {
    align: center middle;
    width: 80%;
    max-width: 88;
    height: auto;
    border: thick $warning;
    background: $surface;
    padding: 1 2;
}
"""


class ApprovalScreen(ModalScreen[str]):
    """Foreground approval card — Pi-style, never buried in logs."""

    BINDINGS = [("escape", "deny", "Deny"), ("q", "deny", "Stop")]

    def __init__(self, tool: str, summary: str, mandatory: bool = False) -> None:
        super().__init__()
        self._tool = tool
        self._summary = summary
        self._mandatory = mandatory

    def compose(self) -> ComposeResult:
        yield Static(f"[bold yellow]Approval required[/]\n[bold]{self._tool}[/]\n{self._summary}", id="body")
        with Vertical():
            yield Button("Allow once (a)", id="allow", variant="success")
            yield Button("Allow session (s)", id="session", variant="primary")
            if not self._mandatory:
                yield Button("Allow always (p)", id="always", variant="default")
            yield Button("Deny (n)", id="deny", variant="error")
            yield Button("Stop run (q)", id="stop", variant="warning")

    @on(Button.Pressed, "#allow")
    def _allow(self) -> None:
        self.dismiss("allow")

    @on(Button.Pressed, "#session")
    def _session(self) -> None:
        self.dismiss("session")

    @on(Button.Pressed, "#always")
    def _always(self) -> None:
        self.dismiss("always")

    @on(Button.Pressed, "#deny")
    def _deny(self) -> None:
        self.dismiss("deny")

    @on(Button.Pressed, "#stop")
    def _stop(self) -> None:
        self.dismiss("stop")


class KiteApp(App[None]):
    """Full-screen Kite session — event stream drives the transcript."""

    CSS = KITE_CSS
    TITLE = "kite"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+p", "plan_mode", "Plan"),
        Binding("ctrl+b", "build_mode", "Build"),
        Binding("ctrl+o", "toggle_expand", "Expand"),
        Binding("escape", "stop_turn", "Stop", show=False),
        Binding("f2", "flash_status", "Status"),
    ]

    def __init__(self, session: ChatSession) -> None:
        super().__init__()
        self.session = session
        self.rich_console = Console(width=120, legacy_windows=False)
        self._turn_done: threading.Event | None = None
        self._turn_waiting = False
        self._quit_requested = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="transcript", highlight=True, markup=True, wrap=True)
        yield Static("", id="flash")
        yield Static("", id="status-line")
        yield Input(placeholder="Ask kite…  (/help · Ctrl+P plan · Ctrl+B build)", id="composer")
        yield Footer()

    def on_mount(self) -> None:
        self.session._textual_app = self
        self.session.display = TextualRunDisplay(self, verbose=self.session.verbose, state=self.session.state)
        self.session.console = self.rich_console
        self.session.state._refresh = self._refresh_status
        from kite.ui.git import git_branch

        self.session.state.git_branch = git_branch(self.session.cwd)
        self._write_banner()
        self.set_interval(0.12, self._poll_turn)
        self.set_interval(0.4, self._refresh_status)
        self.query_one("#composer", Input).focus()

    def _write_banner(self) -> None:
        from kite.config import UserConfig

        cfg = UserConfig.load()
        prov = self.session.provider or cfg.default_provider or "—"
        mod = self.session.model or cfg.default_model or "—"
        line = Text()
        line.append("kite", style="bold cyan")
        line.append(" · ", style="dim")
        line.append(f"{prov}/{mod}", style="bold")
        line.append(" · ", style="dim")
        line.append("/help", style="cyan")
        self.write_transcript(line, markup=False)

    def write_transcript(self, renderable: Any, *, markup: bool = True, highlight: bool = True) -> None:
        log = self.query_one("#transcript", RichLog)
        if isinstance(renderable, str) and markup:
            log.write(renderable)
        else:
            log.write(renderable)

    def _refresh_status(self) -> None:
        from kite.ui.status import format_status_tail, format_running_status

        state = self.session.state
        bits = [format_status_tail(state)]
        running = format_running_status(state)
        if running:
            bits.append(running)
        self.query_one("#status-line", Static).update("  ".join(bits))
        flash = self.query_one("#flash", Static)
        flash.update(state.flash or "")

    def _poll_turn(self) -> None:
        if not self._turn_waiting or self._turn_done is None:
            self._maybe_show_approval()
            return
        self.session._busy_tick()
        self._maybe_show_approval()
        if self._turn_done.is_set():
            self._turn_waiting = False
            self._turn_done = None
            self.session._busy = False
            self.session.state.busy = False
            self.session.state.clear_running()
            self.session.display.flush_transcript_buffer()
            self._refresh_status()

    def _maybe_show_approval(self) -> None:
        req = self.session._approval_coordinator.pending
        if req is None or isinstance(self.screen, ApprovalScreen):
            return
        if self.session.state.awaiting_approval:
            self.push_screen(
                ApprovalScreen(req.tool, req.reason or "", mandatory=bool(getattr(req, "mandatory", False))),
                self._resolve_approval,
            )

    def _resolve_approval(self, decision: str | None) -> None:
        if not decision:
            decision = "deny"
        req = self.session._approval_coordinator.pending
        if req is None:
            return
        self.session._approval_coordinator.resolve(decision, request_id=req.request_id)
        self.session.state.awaiting_approval = ""
        self.session.state.awaiting_approval_mandatory = False

    @on(AgentEventMessage)
    def _on_agent_event(self, message: AgentEventMessage) -> None:
        self.session._apply_ui_event(message.event)

    def post_agent_event(self, event: Event) -> None:
        self.post_message(AgentEventMessage(event))

    def wait_for_turn(self, done: threading.Event) -> None:
        self._turn_done = done
        self._turn_waiting = True

    @on(Input.Submitted, "#composer")
    def _submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self.session._busy or self._turn_waiting:
            self.session._queue_message(text)
            self.post_message(StatusFlashMessage(f"queued: {text[:60]}"))
            return
        from kite.cli.slash import resolve_slash

        parsed = resolve_slash(text, self.session._index())
        if parsed.kind != "not_slash":
            if not self.session._handle_slash(text, parsed):
                self.exit()
            return
        self._run_turn(text)

    @work(thread=True)
    def _run_turn(self, task: str) -> None:
        self.session._run_task_textual(task)

    def action_quit(self) -> None:
        self.session._teardown_jobs()
        self.exit()

    def action_plan_mode(self) -> None:
        self.session._slash_plan("")
        self.post_message(StatusFlashMessage("plan mode"))

    def action_build_mode(self) -> None:
        self.session._slash_build("")
        self.post_message(StatusFlashMessage("build mode"))

    def action_toggle_expand(self) -> None:
        self.session._slash_expand("")
        self.post_message(StatusFlashMessage("toggled expand"))

    def action_stop_turn(self) -> None:
        if self.session._busy:
            self.session._request_stop()
            self.post_message(StatusFlashMessage("stopping…"))

    def action_flash_status(self) -> None:
        from kite.ui.status import format_status_tail

        self.post_message(StatusFlashMessage(format_status_tail(self.session.state)))

    @on(StatusFlashMessage)
    def _on_flash(self, message: StatusFlashMessage) -> None:
        self.session.state.set_flash(message.text)
        self._refresh_status()


def should_use_textual_tui() -> bool:
    if os.environ.get("KITE_LEGACY_TUI", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if not sys.stdin.isatty():
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True
