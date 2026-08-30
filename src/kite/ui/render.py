"""Core render loop: history cells, not mixed token soup.

Codex: user / thinking / answer / exec as separate cells.
Antigravity: effort on the footer, compaction as a boundary, tools as rows.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.diff import render_diff
from kite.ui.spinner import WaitSpinner
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.style import (
    CHANNEL_PREFIX,
    COLLAPSE_LINES,
    GUTTER,
    SYMBOL_COLLAPSE,
    SYMBOL_COMPACT,
    SYMBOL_FAIL,
    SYMBOL_OK,
    SYMBOL_REASON,
    SYMBOL_SEP,
    SYMBOL_SPIN,
    SYMBOL_TODO,
    SYMBOL_USER,
    SYMBOL_WARN,
    make_console,
)


def _format_duration(ms: int | None) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _render_tool_block(tool: str, args: dict[str, Any], *, structured: dict[str, Any] | None = None) -> Text:
    """Warp-style command block header — one scannable row."""
    line = Text()
    line.append(f"{SYMBOL_COLLAPSE} ", style="kite.tool")
    line.append(tool, style="kite.tool bold")

    s = structured or {}
    target = s.get("command") or s.get("target") or _short_args(args)
    if target:
        line.append("  ")
        line.append(str(target)[:100], style="kite.muted")

    duration = _format_duration(s.get("duration_ms"))
    exit_code = s.get("exit_code")
    meta_bits: list[str] = []
    if duration:
        meta_bits.append(duration)
    if exit_code is not None:
        meta_bits.append(f"exit={exit_code}")
    if meta_bits:
        line.append("  ")
        line.append(" ".join(meta_bits), style="kite.muted")
    return line


def render_reasoning_block(text: str, *, step: int | None = None) -> Text:
    """Structured reasoning cell — distinct from answer, never mixed."""
    t = Text()
    prefix = f"{SYMBOL_REASON} "
    if step is not None:
        prefix = f"{SYMBOL_REASON} [{step}] "
    for i, line in enumerate(text.splitlines() or [text]):
        t.append(prefix if i == 0 else "    ", style="kite.thinking")
        t.append(line + "\n", style="kite.thinking")
    return t


def render_loop_warning(message: str) -> Text:
    t = Text()
    t.append(f"{SYMBOL_WARN} ", style="kite.pending")
    t.append("loop  ", style="kite.pending bold")
    t.append(message.strip(), style="kite.pending")
    t.append("\n")
    return t


def _short_args(args: dict[str, Any], limit: int = 120) -> str:
    if not args:
        return ""
    skip = {"content", "old", "new", "reason"}
    for key in ("path", "command", "pattern", "query", "name", "prompt", "url"):
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
    if state.reasoning and state.reasoning != "auto":
        effort_style = "kite.pending" if state.reasoning == "thinking" else "kite.muted"
        t.append(f" {SYMBOL_SEP} {state.reasoning}", style=effort_style)
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


def render_user_cell(task: str) -> Text:
    """Codex user cell: › first line, then a matching gutter."""
    t = Text()
    lines = task.splitlines() or [task]
    for i, line in enumerate(lines):
        t.append(f"{SYMBOL_USER} " if i == 0 else "  ", style="kite.muted")
        t.append(line + "\n", style="kite.user")
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
        self._channel: str | None = None
        self._need_prefix = False
        self._did_first_line = False
        self._saw_answer = False
        self._spinner = WaitSpinner(label="thinking")
        self._spinner_on = False

    def _stdout_write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _end_stream_line(self) -> None:
        if self._streaming:
            self.console.print()
            self._streaming = False
        self._need_prefix = False

    def _ensure_channel(self, channel: str) -> None:
        """thinking and answer never share a cell."""
        if self._channel == channel:
            return
        had = self._channel is not None
        self._end_stream_line()
        if had:
            self.console.print()
        self._channel = channel
        self._need_prefix = True
        self._did_first_line = False

    def _stream_write(self, text: str, *, channel: str) -> None:
        self._ensure_channel(channel)
        if channel == "answer":
            self._saw_answer = True
        style = "kite.thinking" if channel == "thinking" else "kite.answer"
        prefix = CHANNEL_PREFIX.get(channel, "  ")
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                self.console.print()
                self._need_prefix = True
            if self._need_prefix and part:
                indent = prefix if not self._did_first_line else "  "
                self.console.print(indent, style=style, end="", highlight=False, markup=False)
                self._need_prefix = False
                self._did_first_line = True
            if part:
                self.console.print(part, style=style, end="", highlight=False, markup=False)
                self._streaming = True
            elif i > 0:
                self._streaming = True

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
        if task:
            self.console.print(render_user_cell(task), highlight=False)

    def __call__(self, event: Event) -> None:
        if self.quiet:
            return
        kind = event.kind
        p = event.payload

        if kind == "attach":
            name = str(p.get("name") or "")
            source = str(p.get("source") or "file")
            kind_label = str(p.get("kind") or "")
            extra = f"  {kind_label}" if kind_label and kind_label != "text" else ""
            self.console.print(f"[kite.muted]attach  {source}  {name}{extra}[/]")
            return

        if kind == "route":
            reason = str(p.get("reason") or "")
            if reason == "vision":
                self.console.print(
                    f"[kite.muted]vision  {p.get('provider')}/{p.get('model')}[/]"
                )
            else:
                self.console.print("[kite.muted]no vision model on selected providers — image noted, not sent[/]")
            return

        if kind == "agent_start":
            self.state.provider = str(p.get("provider") or self.state.provider)
            self.state.model = str(p.get("model") or self.state.model)
            self.state.interrupted = False
            self.print_banner(str(p.get("task") or "").strip())
            self.print_plan()
            self._channel = None
            self._saw_answer = False
            self._spin(True, "thinking")
            return

        if kind == "stream_start":
            self._end_stream_line()
            self.state.provider = str(p.get("provider") or self.state.provider)
            self.state.model = str(p.get("model") or self.state.model)
            self.state.n_calls += 1
            self._channel = None
            self._streaming = False
            self._spin(True, "thinking")
            return

        if kind == "stream_reasoning":
            text = p.get("text") or ""
            if text:
                self._spin(False)
                self._stream_write(text, channel="thinking")
            else:
                self._spin(True, "thinking")
            return

        if kind == "stream_delta":
            text = p.get("text") or ""
            if text:
                self._spin(False)
                self._stream_write(text, channel="answer")
            else:
                self._spin(True, "thinking")
            return

        if kind == "stream_tool":
            name = p.get("name") or "?"
            self._spin(True, f"working  {name}")
            return

        if kind == "stream_end":
            self._end_stream_line()
            self._channel = None
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
            self.console.print(_render_tool_block(tool, args))
            if reason:
                self.console.print(Text(f"{GUTTER}{GUTTER}{reason}", style="kite.muted"))
            if tool == "bash" and args.get("command"):
                cmd = str(args["command"]).strip()
                for cmd_line in cmd.splitlines():
                    self.console.print(Text(f"{GUTTER}{GUTTER}$ {cmd_line}", style="kite.muted"))
            self._spin(True, f"working  {tool}")
            return

        if kind == "tool_end":
            self._end_stream_line()
            self._spin(False)
            tool = str(p.get("tool") or "tool")
            args_preview = p.get("structured") if isinstance(p.get("structured"), dict) else {}
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
            duration = _format_duration(p.get("duration_ms"))
            exit_code = p.get("structured", {}).get("exit_code") if isinstance(p.get("structured"), dict) else p.get("exit_code")
            meta: list[str] = []
            if duration:
                meta.append(duration)
            if exit_code is not None:
                meta.append(f"exit={exit_code}")
            if meta:
                line.append("  ")
                line.append(" ".join(meta), style="kite.muted")
            preview = p.get("preview")
            if preview and not duration:
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

        if kind == "loop_warning":
            self._end_stream_line()
            self._spin(False)
            self.console.print(render_loop_warning(str(p.get("message") or "")))
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
            self.console.print(f"[kite.muted]{SYMBOL_SEP} {' '.join(str(b) for b in bits)}[/]")
            return

        if kind == "compact":
            self._end_stream_line()
            self.console.print(
                f"[kite.muted]{SYMBOL_COMPACT}  {p.get('before')} → {p.get('after')}[/]"
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
                if submission and not self._saw_answer:
                    self._stream_write(submission, channel="answer")
                    self._end_stream_line()
            elif status in {"Interrupted", "Denied"}:
                self.console.print(Text(str(status).lower(), style="kite.pending"))
            else:
                self.console.print(render_error(str(status), show_trace_hint=False))
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
