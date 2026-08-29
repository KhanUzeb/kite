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
from kite.ui.chips import render_plan_tasks, render_tool_chip, render_tool_chip_done
from kite.ui.diff import render_diff
from kite.ui.spinner import WaitSpinner
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import approval_style, mode_style
from kite.ui.style import (
    CHANNEL_PREFIX,
    COLLAPSE_LINES,
    GUTTER,
    SYMBOL_COLLAPSE,
    SYMBOL_COMPACT,
    SYMBOL_EXPAND,
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
        glyph = SYMBOL_EXPAND if expanded else SYMBOL_COLLAPSE
        hint = "/collapse" if expanded else "/expand"
        out.append(
            f"{GUTTER}{GUTTER}{glyph} +{extra} lines  {hint}\n",
            style="kite.muted",
        )
    return out


def render_turn_boundary(turn: int) -> Text:
    t = Text()
    t.append(f"{GUTTER}turn {turn}\n", style="kite.muted")
    return t


def render_compact_boundary(before: int | str, after: int | str) -> Text:
    t = Text()
    t.append(f"{GUTTER}{SYMBOL_COMPACT}  ", style="kite.muted")
    t.append(f"{before} → {after}", style="kite.muted")
    t.append("\n")
    return t


def render_plan(todos: list[TodoItem]) -> Text:
    t = Text()
    if not todos:
        return t
    done = sum(1 for item in todos if item.status == "completed")
    t.append(f"plan  ({done}/{len(todos)})\n", style="kite.plan")
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
    from kite.ui.status import context_meter

    t = Text()
    t.append("kite", style="kite.brand")
    t.append(f" {SYMBOL_SEP} ", style="kite.muted")
    t.append(state.mode.value, style=mode_style(state))
    t.append(f" {SYMBOL_SEP} ", style="kite.muted")
    t.append(state.approval.value, style=approval_style(state))
    model = f"{state.provider}/{state.model}" if state.provider else (state.model or "—")
    meta: list[str] = [model]
    if state.reasoning and state.reasoning != "auto":
        meta.append(state.reasoning)
    if state.pending_attach:
        meta.append(f"+{state.pending_attach}")
    if state.active_subagents:
        meta.append(f"agents {state.active_subagents}")
    meter = context_meter(state.context_pct)
    if meter:
        meta.append(meter)
    elif state.tokens and state.window:
        meta.append(f"ctx {state.tokens}/{state.window}")
    if state.cache_hit_tokens > 0:
        meta.append(f"cache {state.cache_hit_ratio:.0%}")
    meta.append(f"${state.cost:.3f}")
    if state.git_branch:
        meta.append(state.git_branch)
    if state.interrupted:
        meta.append("interrupted")
    t.append(f" {SYMBOL_SEP} ".join(meta), style="kite.muted")
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
        self._plan_printed = False
        self._anim_tick = 0
        self._thinking_open = False

    def _touch_state(self) -> None:
        self.state.touch()

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
            self._anim_tick += 1
            fast = label.startswith(("working", "subagent"))
            if not self._spinner_on:
                self._spinner.start()
                self._spinner_on = True
            self._spinner.kick(label, fast=fast)
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
        self._plan_printed = True
        self.console.print(render_plan_tasks(self.state.todos, tick=self._anim_tick))

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
            self._plan_printed = False
            self._thinking_open = False
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
                if not self._thinking_open:
                    self.console.print(Text(f"{GUTTER}Thinking", style="kite.thinking bold"))
                    self._thinking_open = True
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
            self._thinking_open = False
            self._spin(True, "working")
            return

        if kind == "turn_start":
            self.state.turn += 1
            self._touch_state()
            return

        if kind == "turn_end":
            self._end_stream_line()
            self._spin(True, "thinking")
            self._touch_state()
            return

        if kind == "tool_start":
            self._end_stream_line()
            tool = str(p.get("tool") or "?")
            args = p.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            reason = str(args.get("reason") or p.get("reason") or "")
            detail = _short_args(args, limit=60)
            self.console.print(render_tool_chip(tool, detail, running=True))
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
            ok = p.get("ok", True)
            blocked = bool(p.get("blocked"))
            duration = _format_duration(p.get("duration_ms"))
            exit_code = p.get("structured", {}).get("exit_code") if isinstance(p.get("structured"), dict) else p.get("exit_code")
            meta: list[str] = []
            if duration:
                meta.append(duration)
            if exit_code is not None:
                meta.append(f"exit={exit_code}")
            self.console.print(
                render_tool_chip_done(tool, ok=ok, warn=blocked, meta=" ".join(meta) if meta else "")
            )

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
                redacted = p.get("secrets_redacted")
                expanded = self.verbose or self.state.expanded_all
                collapsed = _collapse_text(output, expanded=expanded)
                if collapsed.plain:
                    self.console.print(collapsed)
                if redacted:
                    self.console.print(Text(f"{GUTTER}{GUTTER}· {redacted} secret(s) redacted", style="kite.muted"))
            return

        if kind == "artifact":
            self._end_stream_line()
            self._spin(False)
            status = str(p.get("status") or "unknown")
            style = "kite.success" if status == "verified" else ("kite.pending" if status == "partial" else "kite.error")
            line = Text()
            line.append(f"{SYMBOL_OK if status == 'verified' else SYMBOL_WARN} ", style=style)
            line.append(f"artifacts  {status}", style=style)
            count = p.get("artifact_count")
            if count:
                line.append(f"  ({count})", style="kite.muted")
            self.console.print(line)
            for art in (p.get("artifacts") or [])[-5:]:
                if isinstance(art, dict):
                    mark = "✓" if art.get("ok", True) else "✗"
                    self.console.print(
                        Text(f"{GUTTER}{mark} [{art.get('kind', '?')}] {art.get('summary', '')}", style="kite.muted")
                    )
            for gap in p.get("gaps") or []:
                self.console.print(Text(f"{GUTTER}⚠ {gap}", style="kite.pending"))
            return

        if kind == "cost_estimate":
            note = str(p.get("note") or "")
            if note:
                self.console.print(Text(f"{GUTTER}{note}", style="kite.muted"))
            return

        if kind == "cost_warning":
            msg = str(p.get("message") or "cost warning")
            line = Text()
            line.append(f"{SYMBOL_WARN} ", style="kite.pending")
            line.append(msg, style="kite.pending")
            ratio = p.get("ratio") or p.get("pct")
            if ratio is not None:
                try:
                    pct = max(0.0, min(1.0, float(ratio)))
                    filled = int(round(pct * 10))
                    bar = "█" * filled + "░" * (10 - filled)
                    line.append(f"  {bar} {pct:.0%}", style="kite.muted")
                except (TypeError, ValueError):
                    pass
            line.append("\n")
            self.console.print(line)
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
            if isinstance(total, int):
                self.state.tokens = total
            if isinstance(window, int):
                self.state.window = window
            self._touch_state()
            if self.verbose:
                ratio = p.get("ratio")
                bits = [f"ctx {total}/{window}"]
                if ratio is not None:
                    bits.append(f"{ratio:.0%}" if isinstance(ratio, float) else str(ratio))
                self.console.print(f"[kite.muted]{SYMBOL_SEP} {' '.join(str(b) for b in bits)}[/]")
            return

        if kind == "compact":
            self._end_stream_line()
            self.console.print(render_compact_boundary(p.get("before", "?"), p.get("after", "?")))
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
            tool = str(p.get("tool") or "action")
            self.console.print(Text(f"{SYMBOL_WARN}  waiting  {tool}", style="kite.pending"))
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
                vstatus = p.get("verification_status")
                if vstatus in {"unverified", "failed", "partial"}:
                    self.console.print(
                        Text(
                            f"{SYMBOL_WARN} verification: {vstatus} — review artifacts above",
                            style="kite.pending",
                        )
                    )
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
            self._touch_state()
            return

        if kind == "cache_hit":
            session = p.get("session") if isinstance(p.get("session"), dict) else {}
            hits = int(session.get("cache_hit_tokens") or p.get("cache_read") or p.get("cached") or 0)
            if hits:
                self.state.cache_hit_tokens = hits
                try:
                    self.state.cache_hit_ratio = float(session.get("hit_ratio") or 0.0)
                except (TypeError, ValueError):
                    pass
                self._touch_state()
                if self.verbose:
                    self.console.print(
                        f"[kite.muted]{GUTTER}cache hit  {hits} tokens ({self.state.cache_hit_ratio:.0%})[/]"
                    )
            return

        if kind == "subagent_start":
            self._end_stream_line()
            label = str(p.get("label") or p.get("id") or "subagent")
            self.state.active_subagents += 1
            self._touch_state()
            self.console.print(Text(f"{GUTTER}{SYMBOL_COLLAPSE} subagent  {label}", style="kite.plan"))
            self._spin(True, f"subagent  {label}")
            return

        if kind == "subagent_end":
            self._spin(False)
            label = str(p.get("label") or p.get("id") or "subagent")
            ok = p.get("ok", True)
            mark = SYMBOL_OK if ok else SYMBOL_FAIL
            style = "kite.success" if ok else "kite.error"
            self.state.active_subagents = max(0, self.state.active_subagents - 1)
            self._touch_state()
            self.console.print(Text(f"{GUTTER}{mark} subagent  {label}", style=style))
            preview = str(p.get("preview") or "")
            if preview:
                self.console.print(Text(f"{GUTTER}{GUTTER}{preview[:100]}", style="kite.muted"))
            return

        if kind == "warning":
            msg = str(p.get("message") or "").strip()
            if msg:
                self.console.print(Text(f"{GUTTER}{SYMBOL_WARN} {msg}", style="kite.muted"))
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
