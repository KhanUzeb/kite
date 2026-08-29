"""Core render loop: stream → collapse/expand tools → diffs → approval → footer.

Single-column, keyboard-first. Console chrome on stderr so token streaming
on stdout never fights Rich markup.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.diff import render_diff
from kite.ui.spinner import WaitSpinner
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.style import (
    COLLAPSE_LINES,
    GUTTER,
    SYMBOL_COLLAPSE,
    SYMBOL_COMPACT,
    SYMBOL_FAIL,
    SYMBOL_OK,
    SYMBOL_SEP,
    SYMBOL_SPIN,
    SYMBOL_TODO,
    SYMBOL_WARN,
    make_console,
)


def _short_args(args: dict[str, Any], limit: int = 120) -> str:
    if not args:
        return ""
    skip = {"content", "old", "new", "reason"}
    for key in ("path", "command", "pattern", "query", "name", "prompt"):
        if key in args and args[key] is not None:
            val = str(args[key]).replace("\n", " ")
            if len(val) > limit:
                val = val[: limit - 1] + "…"
            return f"{key}={val}"
    preview = json.dumps({k: v for k, v in args.items() if k not in skip}, ensure_ascii=False)
    if len(preview) > limit:
        preview = preview[: limit - 1] + "…"
    return preview


def _collapse_text(text: str, *, expanded: bool, limit: int = COLLAPSE_LINES) -> Text:
    raw = text.rstrip("\n")
    if not raw:
        return Text()
    lines = raw.splitlines()
    out = Text()
    shown = lines if expanded else lines[:limit]
    for line in shown:
        out.append(f"{GUTTER}{GUTTER}{line}\n", style="kite.muted")
    extra = len(lines) - len(shown)
    if extra > 0:
        out.append(
            f"{GUTTER}{GUTTER}{SYMBOL_COLLAPSE} +{extra} lines  /expand\n",
            style="kite.muted",
        )
    return out


def render_plan(todos: list[TodoItem]) -> Text:
    t = Text()
    if not todos:
        return t
    t.append("plan\n", style="kite.plan")
    for item in todos:
        if item.status == "completed":
            mark, style = SYMBOL_OK, "kite.success"
        elif item.status == "in_progress":
            mark, style = SYMBOL_SPIN, "kite.pending"
        else:
            mark, style = SYMBOL_TODO, "kite.muted"
        t.append(f"{GUTTER}{mark} ", style=style)
        t.append(f"{item.content}\n", style=style if item.status != "pending" else "kite.muted")
    return t


def render_status(state: SessionUiState) -> Text:
    t = Text()
    t.append("kite", style="kite.brand")
    t.append(f" {SYMBOL_SEP} ")
    mode_style = "kite.plan" if state.mode is AgentMode.PLAN else "kite.build"
    t.append(state.mode.value, style=mode_style)
    t.append(f" {SYMBOL_SEP} ")
    t.append(state.approval.value, style="kite.pending" if state.approval is ApprovalMode.APPROVE else "kite.muted")
    model = f"{state.provider}/{state.model}" if state.provider else (state.model or "—")
    t.append(f" {SYMBOL_SEP} {model}")
    if state.context_pct is not None:
        t.append(f" {SYMBOL_SEP} ctx {state.context_pct:.0%}", style="kite.muted")
    t.append(f" {SYMBOL_SEP} ${state.cost:.3f}", style="kite.muted")
    if state.git_branch:
        t.append(f" {SYMBOL_SEP} {state.git_branch}", style="kite.muted")
    if state.interrupted:
        t.append("  interrupted", style="kite.error")
    return t


def render_error(message: str, *, show_trace_hint: bool = True) -> Text:
    t = Text()
    t.append(f"{SYMBOL_FAIL} ", style="kite.error")
    t.append(message.strip() or "error", style="kite.error")
    if show_trace_hint:
        t.append("  /trace", style="kite.muted")
    t.append("\n")
    return t


class RunDisplay:
    """Stateful event sink — the core render loop."""

    def __init__(
        self,
        console: Console | None = None,
        *,
        quiet: bool = False,
        verbose: bool = False,
        state: SessionUiState | None = None,
    ):
        self.console = console or make_console(stderr=True, quiet=quiet)
        self.quiet = quiet
        self.verbose = verbose
        self.state = state or SessionUiState()
        self._streaming = False
        self._spinner = WaitSpinner(label="thinking")
        self._spinner_on = False

    def _stdout_write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _end_stream_line(self) -> None:
        if self._streaming:
            self._stdout_write("\n")
            self._streaming = False

    def _spin(self, on: bool, label: str = "thinking") -> None:
        if on and not self.quiet:
            if not self._spinner_on:
                self._spinner.start()
                self._spinner_on = True
            self._spinner.kick(label)
        else:
            if self._spinner_on:
                self._spinner.stop()
                self._spinner_on = False

    def close(self) -> None:
        self._spin(False)
        self._end_stream_line()

    def print_status(self) -> None:
        if not self.quiet:
            self.console.print(render_status(self.state), highlight=False)

    def print_plan(self) -> None:
        if self.quiet or not self.state.todos:
            return
        self.console.print(render_plan(self.state.todos))

    def print_banner(self, task: str = "") -> None:
        header = Text()
        header.append("kite", style="kite.brand")
        header.append(f"  {self.state.mode.value}", style="kite.plan" if self.state.mode is AgentMode.PLAN else "kite.build")
        if self.state.provider or self.state.model:
            header.append(
                f"  {self.state.provider}/{self.state.model}",
                style="kite.muted",
            )
        self.console.print(header)
        if task:
            self.console.print(Panel(escape(task), title="you", border_style="cyan", padding=(0, 1)))

    def __call__(self, event: Event) -> None:
        if self.quiet:
            return
        kind = event.kind
        p = event.payload

        if kind == "agent_start":
            self.state.provider = str(p.get("provider") or self.state.provider)
            self.state.model = str(p.get("model") or self.state.model)
            self.state.interrupted = False
            self.print_banner(str(p.get("task") or "").strip())
            self.print_plan()
            self._spin(True, "starting")
            return

        if kind == "stream_start":
            self._end_stream_line()
            self.state.provider = str(p.get("provider") or self.state.provider)
            self.state.model = str(p.get("model") or self.state.model)
            self.state.n_calls += 1
            label = f"{self.state.provider}/{self.state.model}" if self.state.provider else "assistant"
            self.console.print(f"[kite.assistant]{escape(label)}[/]")
            self._streaming = True
            self._spin(True, "thinking")
            return

        if kind == "stream_delta":
            text = p.get("text") or ""
            if text:
                self._spin(False)
                self._stdout_write(text)
                self._streaming = True
            else:
                self._spin(True, "thinking")
            return

        if kind == "stream_tool":
            name = p.get("name") or "?"
            self._spin(True, f"tool {name}")
            return

        if kind == "stream_end":
            self._end_stream_line()
            self._spin(True, "working")
            if p.get("ok") is False:
                self.console.print("[kite.muted](stream ended)[/]")
            return

        if kind == "tool_start":
            self._end_stream_line()
            tool = str(p.get("tool") or "?")
            args = p.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            reason = str(args.get("reason") or p.get("reason") or "")
            line = Text()
            line.append(f"{SYMBOL_COLLAPSE} ", style="kite.tool")
            line.append(tool, style="kite.tool")
            detail = _short_args(args)
            if detail:
                line.append("  ")
                line.append(detail, style="kite.muted")
            if reason:
                line.append("  ")
                line.append(reason, style="kite.muted")
            self.console.print(line)
            self._spin(True, f"{tool}")
            return

        if kind == "tool_end":
            self._end_stream_line()
            self._spin(False)
            tool = str(p.get("tool") or "tool")
            ok = p.get("ok", True)
            blocked = bool(p.get("blocked"))
            if blocked:
                mark, style = SYMBOL_WARN, "kite.pending"
            elif ok:
                mark, style = SYMBOL_OK, "kite.success"
            else:
                mark, style = SYMBOL_FAIL, "kite.error"
            line = Text()
            line.append(f"{mark} ", style=style)
            line.append(tool, style=style)
            preview = p.get("preview")
            if preview and self.verbose:
                line.append("  ")
                line.append(str(preview)[:80], style="kite.muted")
            self.console.print(line)

            diff = p.get("diff")
            if isinstance(diff, str) and diff.strip():
                self.console.print(
                    render_diff(diff, collapsed=not (self.verbose or self.state.expanded_all))
                )
            elif not ok:
                err = str(p.get("error") or p.get("output") or "")
                if err:
                    self.console.print(render_error(err.splitlines()[0], show_trace_hint=False))
            else:
                output = str(p.get("output") or "")
                expanded = self.verbose or self.state.expanded_all
                collapsed = _collapse_text(output, expanded=expanded)
                if collapsed.plain:
                    self.console.print(collapsed)
            return

        if kind == "todo":
            self.state.set_todos(p.get("items") or [])
            self.print_plan()
            return

        if kind == "diff":
            self._end_stream_line()
            self._spin(False)
            diff = str(p.get("diff") or "")
            path = str(p.get("path") or "")
            if path:
                self.console.print(Text(f"{GUTTER}{path}", style="kite.muted"))
            if diff:
                self.console.print(render_diff(diff, collapsed=not self.verbose))
            return

        if kind == "context":
            total = p.get("total_tokens")
            window = p.get("window")
            ratio = p.get("ratio")
            if isinstance(total, int):
                self.state.tokens = total
            if isinstance(window, int):
                self.state.window = window
            bits = [f"ctx {total}/{window}"]
            if ratio is not None:
                bits.append(f"{ratio:.0%}" if isinstance(ratio, float) else str(ratio))
            self.console.print(f"[kite.muted]{' · '.join(str(b) for b in bits)}[/]")
            return

        if kind == "compact":
            self._end_stream_line()
            self.console.print(
                f"[kite.pending]{SYMBOL_COMPACT} compacted[/] {p.get('before')} → {p.get('after')} msgs"
            )
            return

        if kind == "commit":
            self._end_stream_line()
            self._spin(False)
            sha = str(p.get("sha") or "")
            msg = str(p.get("message") or "commit")
            files = p.get("files") or []
            n = len(files) if isinstance(files, list) else 0
            line = Text()
            line.append(f"{SYMBOL_OK} ", style="kite.success")
            line.append("commit  ", style="kite.success")
            line.append(msg, style="kite.muted")
            if sha:
                line.append(f"  {sha}", style="kite.muted")
            if n:
                line.append(f"  ({n} file{'s' if n != 1 else ''})", style="kite.muted")
            self.console.print(line)
            return

        if kind == "interrupt":
            self._end_stream_line()
            self._spin(False)
            self.state.interrupted = True
            self.console.print(f"[kite.error]{SYMBOL_FAIL} stopped[/] [kite.muted]steer and resume[/]")
            return

        if kind == "approval":
            self._end_stream_line()
            self._spin(False)
            return

        if kind == "agent_end":
            self._end_stream_line()
            self._spin(False)
            status = p.get("exit_status") or "done"
            submission = (p.get("submission") or "").strip()
            if status == "Submitted":
                border = "green"
            elif status in {"Interrupted", "Denied"}:
                border = "yellow"
            else:
                border = "red" if "Error" in str(status) else "yellow"
            body = escape(submission) if submission else f"[kite.muted]exit_status={escape(str(status))}[/]"
            self.console.print(Panel(body, title=f"result · {status}", border_style=border, padding=(0, 1)))
            self.print_status()
            return

        if kind == "error":
            self._end_stream_line()
            self._spin(False)
            msg = str(p.get("error") or "error")
            self.state.last_error = msg
            self.state.last_trace = str(p.get("traceback") or "")
            self.console.print(render_error(msg, show_trace_hint=bool(self.state.last_trace)))
            return

        if kind == "cost":
            try:
                self.state.cost = float(p.get("cost") or self.state.cost)
            except (TypeError, ValueError):
                pass
            return

        if kind == "mode":
            try:
                self.state.mode = AgentMode(str(p.get("mode")))
            except ValueError:
                pass
            if p.get("approval"):
                try:
                    self.state.approval = ApprovalMode(str(p.get("approval")))
                except ValueError:
                    pass
            self.print_status()
            return


def make_run_display(
    console: Console,
    *,
    quiet: bool,
    verbose: bool,
    state: SessionUiState | None = None,
) -> RunDisplay:
    return RunDisplay(console, quiet=quiet, verbose=verbose, state=state)
