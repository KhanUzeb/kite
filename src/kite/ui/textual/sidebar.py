"""Tau-style sidebar — sessions, crew, git changes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from kite.ui.repl import ChatSession

PANELS = ("sessions", "crew", "changes")


class Sidebar(Vertical):
    """Collapsible left rail with sessions / crew / changes."""

    DEFAULT_CSS = """
    Sidebar {
        width: 34;
        min-width: 28;
        border: solid $primary;
        padding: 0 1;
        background: $surface;
    }
    Sidebar.hidden {
        display: none;
    }
    #sidebar-body {
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, session: ChatSession, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._panel = "sessions"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Button("Sessions", id="tab-sessions", variant="primary")
            yield Button("Crew", id="tab-crew")
            yield Button("Changes", id="tab-changes")
        yield Static("", id="sidebar-body", markup=True)

    def on_mount(self) -> None:
        self.refresh_panel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "tab-sessions": "sessions",
            "tab-crew": "crew",
            "tab-changes": "changes",
        }
        panel = mapping.get(event.button.id or "")
        if not panel:
            return
        self._panel = panel
        for name, btn_id in [("sessions", "tab-sessions"), ("crew", "tab-crew"), ("changes", "tab-changes")]:
            btn = self.query_one(f"#{btn_id}", Button)
            btn.variant = "primary" if name == panel else "default"
        self.refresh_panel()

    def refresh_panel(self) -> None:
        body = self.query_one("#sidebar-body", Static)
        if self._panel == "sessions":
            body.update(self._render_sessions())
        elif self._panel == "crew":
            body.update(self._render_crew())
        else:
            body.update(self._render_changes())

    def _render_sessions(self) -> str:
        from kite.memory.session import list_sessions
        from kite.memory.session_format import format_session_picker_label

        rows = list_sessions(limit=12)
        if not rows:
            return "[dim]no sessions[/]\n[dim]/resume to continue[/]"
        lines = ["[bold]Sessions[/]", ""]
        for meta in rows:
            mark = "[green]●[/] " if meta.id == self.session._session_id else ""
            label = format_session_picker_label(meta)[:48]
            lines.append(f"{mark}{label}")
        lines.append("")
        lines.append("[dim]/resume · /sessions[/]")
        return "\n".join(lines)

    def _render_crew(self) -> str:
        jobs = [j for j in self.session.jobs.list(active_only=False) if j.kind == "subagent"]
        if not jobs:
            return "[dim]crew idle[/]\n[dim]/agents profiles[/]"
        lines = ["[bold]Crew[/]", ""]
        for job in jobs[-10:]:
            status = job.status or "running"
            preview = (job.command or job.label or "").replace("\n", " ")[:36]
            lines.append(f"[cyan]{job.id[:8]}[/] [dim]{status}[/]")
            lines.append(f"  {preview}")
        active = sum(1 for j in jobs if j.status == "running")
        lines.append("")
        lines.append(f"[dim]{active} running · /kill[/]")
        return "\n".join(lines)

    def _render_changes(self) -> str:
        cwd = Path(self.session.cwd)
        try:
            proc = subprocess.run(
                ["git", "diff", "--numstat", "HEAD"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "[dim]git unavailable[/]"
        if proc.returncode != 0:
            return "[dim]not a git repo[/]"
        lines = ["[bold]Changes[/]", ""]
        rows = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if not rows:
            lines.append("[dim]clean working tree[/]")
            return "\n".join(lines)
        for row in rows[:12]:
            parts = row.split("\t")
            if len(parts) < 3:
                continue
            added, deleted, path = parts[0], parts[1], parts[2]
            lines.append(f"[green]+{added}[/] [red]-{deleted}[/] {path[-36:]}")
        if len(rows) > 12:
            lines.append(f"[dim]… +{len(rows) - 12} more[/]")
        return "\n".join(lines)
