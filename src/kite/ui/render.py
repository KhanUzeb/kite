"""Core render loop: history cells, not mixed token soup."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.chips import render_plan_tasks
from kite.ui.diff import count_diff_lines, render_diff
from kite.ui.spinner import WaitSpinner
from kite.ui.state import SessionUiState
from kite.ui.status import render_status
from kite.ui.streaming import StreamCoalescer
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
    SYMBOL_USER,
    SYMBOL_WARN,
    cell_continuation_indent,
    make_console,
)
from kite.ui.theme import glyph, user_surface_styles
from kite.ui.tool_cards import (
    ToolCard,
    detail_from_args,
    format_partial_args,
    line_count_from_output,
    render_bash_command_block,
    render_code_edit_preview,
    render_parallel_batch_header,
    render_run_meter,
    render_section_break,
    render_stream_tool_preview,
    render_tool_card_done,
    render_tool_card_start,
    render_tool_summary,
)

_QUIET_START_TOOLS = frozenset({"read", "grep", "glob", "ls"})


def _looks_like_turn_report(text: str) -> bool:
    """Detect a Done/Changed/Verification turn report (submit template) vs. a real answer."""
    lowered = text.lower()
    return "## done" in lowered or "## changed" in lowered or "## verification" in lowered


def _ellipsize(text: str, limit: int) -> str:
    """Shorten an overlong card segment so narrow terminals don't wrap mid-token."""
    text = text or ""
    if len(text) <= limit or limit <= 1:
        return text
    return text[: limit - 1] + "…"


def render_startup_card(
    *,
    version: str,
    provider: str,
    model: str,
    workspace: str,
    context_files: list[str],
    mode: str = "build",
    compact: bool = False,
) -> Panel:
    """Branded welcome card printed once above the composer.

    Pure presentation: the caller supplies every value, so this stays testable at
    any width and never triggers provider/config work on the startup path.
    Overlong identity/workspace segments are ellipsized so the card never
    wraps mid-token on narrow terminals.
    """
    body = Text()
    blurb = (
        "A lightweight coding agent for your terminal."
        if compact
        else "A lightweight coding agent for inspecting, editing, and verifying code."
    )
    body.append(blurb + "\n", style="kite.muted")
    body.append(_ellipsize(f"{provider}/{model}", 48), style="kite.highlight")
    body.append(f" · {mode} · ", style="kite.muted")
    body.append(_ellipsize(workspace, 32), style="kite.muted")
    shown_files = list(context_files or [])[:3]
    if shown_files:
        body.append(" · ", style="kite.muted")
        body.append(" · ".join(_ellipsize(name, 32) for name in shown_files), style="kite.muted")
        extra = len(context_files or []) - len(shown_files)
        if extra > 0:
            body.append(f" · +{extra} more", style="kite.muted")
    body.append("\n")
    body.append("/help", style="kite.brand")
    body.append(" commands · /model switch · @file attach", style="kite.muted")
    return Panel(
        body,
        title=f"{glyph('kite')} Kite {version}",
        title_align="left",
        border_style="kite.brand",
        padding=(0, 1),
        expand=True,
    )


def _subagent_prefix(p: dict[str, Any]) -> str:
    glyph = str(p.get("subagent_glyph") or "")
    label = str(p.get("subagent_label") or p.get("subagent_id") or "")
    if not label and not glyph:
        return ""
    return f"{glyph} {label}  ·  " if glyph else f"{label}  ·  "


def _live_stream_enabled(state: SessionUiState, p: dict[str, Any]) -> bool:
    if p.get("subagent_id") or p.get("subagent_label"):
        return state.live_subagents or state.live_terminal
    return state.live_terminal


def _format_duration(ms: int | None) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"

def _tool_meta(duration_ms: int | None, exit_code: int | None) -> str:
    bits: list[str] = []
    duration = _format_duration(duration_ms)
    if duration:
        bits.append(duration)
    if exit_code is not None:
        bits.append(f"exit={exit_code}")
    return " ".join(bits)

def render_thinking_summary(chars: int, lines: int, *, expanded_hint: bool = True) -> Text:
    t = Text()
    t.append(f"{GUTTER}{SYMBOL_REASON} ", style="kite.thinking")
    t.append("thinking", style="kite.thinking bold")
    t.append(f"  ·  {lines} line{'s' if lines != 1 else ''} · {chars:,} chars", style="kite.muted")
    if expanded_hint:
        t.append("  ·  Ctrl+T · /expand-thinking", style="kite.muted")
    t.append("\n")
    return t

def render_reasoning_block(text: str, *, step: int | None = None) -> Text:
    from kite.ui.output_view import render_thinking_block

    t = Text()
    if step is not None:
        t.append(f"[{step}]\n", style="kite.muted")
    t.append_text(render_thinking_block(text))
    return t

def render_loop_warning(message: str) -> Text:
    t = Text()
    t.append(f"{SYMBOL_WARN} ", style="kite.pending")
    t.append("stuck in a loop  ", style="kite.pending bold")
    t.append(message.strip(), style="kite.pending")
    t.append("\n")
    return t

def _collapse_text(text: str, *, expanded: bool, limit: int = COLLAPSE_LINES) -> Text:
    from kite.ui.output_view import render_output_block

    return render_output_block(text, expanded=expanded, limit=limit)

def render_compact_boundary(
    before: int | str,
    after: int | str,
    *,
    context_pct: float | None = None,
) -> Text:
    t = Text()
    t.append(f"{GUTTER}{SYMBOL_COMPACT}  ", style="kite.muted")
    t.append(f"{before} → {after}", style="kite.muted")
    if context_pct is not None:
        t.append(f"  · ctx {context_pct:.0%}", style="kite.muted")
    t.append("\n")
    return t

def render_error(message: str, *, show_trace_hint: bool = True, traceback_text: str = "") -> Text:
    t = Text()
    t.append(f"{SYMBOL_FAIL} ", style="kite.error")
    t.append(message.strip() or "error", style="kite.error")
    if traceback_text.strip():
        t.append("\n")
        lines = traceback_text.strip().splitlines()
        tail = lines[-12:] if len(lines) > 12 else lines
        for line in tail:
            t.append(f"{GUTTER}{line}\n", style="kite.muted")
        if len(lines) > len(tail):
            t.append(f"{GUTTER}… {len(lines) - len(tail)} earlier lines  ·  /trace\n", style="kite.muted")
    elif show_trace_hint:
        t.append("  /trace", style="kite.muted")
    t.append("\n")
    return t

def render_user_cell(task: str) -> Padding:
    """Full-width filled band for a submitted user turn."""
    body_style, marker_style, pad_style = user_surface_styles()
    body = Text()
    lines = task.splitlines() or [task]
    user_prefix = f"{SYMBOL_USER} "
    for i, line in enumerate(lines):
        if i:
            body.append("\n")
        body.append(
            user_prefix if i == 0 else cell_continuation_indent(user_prefix),
            style=marker_style,
        )
        body.append(line, style=body_style)
    return Padding(body, (1, 1), style=pad_style, expand=True)


def render_session_transcript(console: Any, session: Any, *, tail: int | None = None) -> None:
    """Print the complete chronological transcript for resume/show paths.

    Renders every persisted message (user, assistant, tool calls/results, system, exit/submit)
    with full multi-line bodies — terminal scrollback keeps long messages readable instead of
    silently truncating them. ``tail`` windows the oldest entries only (None = all).
    """
    from kite.memory.session_format import format_session_resume_hint, transcript_entries

    meta = session.meta
    console.print(f"[kite.muted]{session.id}[/]  {format_session_resume_hint(meta)}")
    entries = transcript_entries(list(session.messages or []))
    if tail is not None:
        shown = entries[-tail:] if tail > 0 else list(entries)
    else:
        shown = entries
    if not shown:
        console.print("[kite.muted](empty transcript)[/]")
        return
    skipped = len(entries) - len(shown)
    if skipped > 0:
        console.print(f"[kite.muted]  … {skipped} earlier messages  ·  use --tail 0 for full[/]")
    from kite.ui.output_view import format_viewable_output

    for entry in shown:
        kind = str(entry.get("kind") or "unknown")
        label = str(entry.get("label") or kind)
        body = str(entry.get("body") or "")
        if kind == "user":
            console.print(render_user_cell(body or "—"), highlight=False)
            continue
        if kind == "assistant":
            if body:
                console.print(Text(body, style="kite.answer"), highlight=False, markup=False)
            for line in entry.get("tool_calls") or []:
                # Text, not markup: persisted tool-call lines may hold brackets.
                console.print(
                    Text(f"  tool: {line}", style="kite.muted"),
                    highlight=False,
                    markup=False,
                )
            if not body and not (entry.get("tool_calls") or []):
                console.print("  [kite.muted]—[/]")
            continue
        if kind == "tool":
            # Labels come from persisted transcripts — never markup-format them.
            console.print(Text(f"  {label}", style="kite.brand"), highlight=False, markup=False)
            viewable = format_viewable_output(body).rstrip("\n") or "—"
            console.print(Text(viewable, style="kite.terminal"), highlight=False, markup=False)
            continue
        if kind == "exit":
            status = str(entry.get("status") or label)
            console.print(Text(f"  {status}", style="kite.brand"), highlight=False, markup=False)
            if body and body != status:
                console.print(Text(body, style="kite.muted"), highlight=False, markup=False)
            continue
        console.print(Text(f"  {label}", style="kite.brand"), highlight=False, markup=False)
        console.print(Text(body or "—", style="kite.muted"), highlight=False, markup=False)


def _composer_owns_bottom(state: SessionUiState) -> bool:
    return state.busy

def _composer_suppresses_scrollprint(state: SessionUiState) -> bool:
    return state.busy

_RENDER_EVENT_KINDS = (
    "attach",
    "route",
    "agent_start",
    "stream_start",
    "stream_first_token",
    "stream_reasoning",
    "stream_delta",
    "stream_tool",
    "stream_usage",
    "stream_end",
    "turn_start",
    "turn_end",
    "tool_start",
    "tool_progress",
    "tool_end",
    "artifact",
    "cost_estimate",
    "cost_warning",
    "loop_warning",
    "todo",
    "diff",
    "context",
    "compact",
    "checkpoint",
    "commit",
    "interrupt",
    "provider_retry",
    "provider_fault",
    "approval",
    "submit_blocked",
    "verification_status",
    "agent_end",
    "error",
    "cost",
    "cache_hit",
    "subagent_start",
    "subagent_end",
    "orchestrator_start",
    "orchestrator_end",
    "job_start",
    "job_end",
    "tool_output",
    "job_output",
    "warning",
    "mode",
    "compaction_start",
    "compaction_end",
)

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
        self._streamed_answer = False
        self._deferred_answer_parts: list[str] = []
        self._deferred_agent_end: dict[str, Any] | None = None
        self._spinner = WaitSpinner(label="thinking")
        self._spinner_on = False
        self._anim_tick = 0
        self._thinking_open = False
        self._thinking_buf: list[str] = []
        self._stream_coalesce = StreamCoalescer()
        self._pending_tool_name: str | None = None
        self._pending_tool_args: str = ""
        self._last_todo_key: str = ""
        self._parallel_batch: int = 0
        self._in_code_fence: bool = False
        self._fence_lang: str = ""
        self._run_tools: int = 0
        self._run_t0: float | None = None
        self._transcript_buffer: list[Any] = []
        # True when a prompt_toolkit composer owns the bottom of the screen: the
        # REPL prints user rows at submit time and the live footer owns status,
        # so event-driven banner/status scroll-printing must stay off.
        self.composer_owns_input = False
        self._event_handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            kind: getattr(self, f"_on_{kind}")  # noqa: SLF001
            for kind in _RENDER_EVENT_KINDS
        }

    def _touch_state(self) -> None:
        self.state.touch()

    def _print(self, *args: Any, **kwargs: Any) -> None:
        self.console.print(*args, **kwargs)

    def flush_transcript_buffer(self) -> None:
        for item in self._transcript_buffer:
            if isinstance(item, tuple):
                self._print(*item)
            else:
                self._print(item, highlight=False, markup=False)
        self._transcript_buffer.clear()

    def _stdout_write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _end_stream_line(self) -> None:
        if self._streaming:
            self._print()
            self._streaming = False
        self._need_prefix = False
        self._answer_line = ""
        self._answer_line_chars = 0

    def _ensure_channel(self, channel: str) -> None:
        if self._channel == channel:
            return
        had = self._channel is not None
        self._end_stream_line()
        if had:
            self._print()
        self._channel = channel
        self._need_prefix = True
        self._did_first_line = False
        self._answer_line = ""
        self._answer_line_chars = 0

    def _answer_style(self) -> str:
        return "kite.terminal" if self._in_code_fence else "kite.answer"

    def _stream_write(self, text: str, *, channel: str) -> None:
        if channel == "answer":
            self._saw_answer = True
            self._streamed_answer = True
            self._stream_write_answer(text)
            return
        if channel == "thinking":
            self._stream_write_thinking(text)
            return
        self._ensure_channel(channel)
        style = "kite.answer"
        prefix = CHANNEL_PREFIX.get(channel, "  ")
        block = Text()
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                block.append("\n")
                self._need_prefix = True
            if self._need_prefix and part:
                indent = prefix if not self._did_first_line else cell_continuation_indent(prefix)
                block.append(indent, style=style)
                self._need_prefix = False
                self._did_first_line = True
            if part:
                block.append(part, style=style)
                self._streaming = True
            elif i > 0:
                self._streaming = True
        if block.plain:
            self._print(block, end="", highlight=False, markup=False)

    def _stream_write_thinking(self, text: str) -> None:
        """Thinking uses the full width — no … gutter (same idea as tool output)."""
        from kite.ui.output_view import format_thinking_text

        self._ensure_channel("thinking")
        chunk = text
        if text.lstrip().startswith("{") and text.rstrip().endswith("}"):
            chunk = format_thinking_text(text)
        block = Text()
        parts = chunk.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                block.append("\n")
                self._need_prefix = True
            if part:
                block.append(part, style="kite.thinking")
                self._need_prefix = False
                self._did_first_line = True
                self._streaming = True
            elif i > 0:
                self._streaming = True
        if block.plain:
            self._print(block, end="", highlight=False, markup=False)

    def _stream_write_answer(self, text: str) -> None:
        """Answer channel — newlines come from the model, never from chunk boundaries."""
        self._ensure_channel("answer")
        while text:
            index = text.find("\n")
            if index < 0:
                self._write_answer_partial(text)
                return
            line, text = text[:index], text[index + 1 :]
            self._write_answer_line(line)

    def _write_answer_partial(self, fragment: str) -> None:
        """Emit a fragment of an unfinished line — no newline, continued in place."""
        if not fragment:
            return
        style, body = self._answer_style(), fragment
        if not self._answer_line_chars and not self._in_code_fence:
            style, body = self._prose_line_style(self._answer_line + fragment)
        block = Text()
        prefix = CHANNEL_PREFIX.get("answer", "  ")
        if self._need_prefix and body:
            indent = prefix if not self._did_first_line else cell_continuation_indent(prefix)
            block.append(indent, style=self._answer_style())
            self._need_prefix = False
            self._did_first_line = True
        block.append(body, style=style)
        self._answer_line += fragment
        self._answer_line_chars += len(fragment)
        self._streaming = True
        self._print(block, end="", highlight=False, markup=False)

    def _write_answer_line(self, line: str) -> None:
        """Close a line — markdown/fence cues apply only when it was not streamed yet."""
        block = Text()
        prefix = CHANNEL_PREFIX.get("answer", "  ")
        if self._answer_line_chars:
            self._write_answer_partial(line)
        elif line:
            stripped = line.strip()
            indent = prefix if not self._did_first_line else cell_continuation_indent(prefix)
            if stripped.startswith("```"):
                opening = not self._in_code_fence
                self._in_code_fence = not self._in_code_fence
                self._fence_lang = stripped.lstrip("`").strip() if opening else ""
                block.append(indent, style="kite.muted")
                self._did_first_line = True
                block.append(
                    f"```{self._fence_lang}" if opening else "```",
                    style="kite.muted italic",
                )
            else:
                style, body = self._prose_line_style(line)
                if body:
                    block.append(indent, style=self._answer_style())
                    self._did_first_line = True
                    block.append(body, style=style)
        self._answer_line = ""
        self._answer_line_chars = 0
        self._need_prefix = True
        self._streaming = True
        block.append("\n")
        self._print(block, end="", highlight=False, markup=False)

    def _prose_line_style(self, line: str) -> tuple[str, str]:
        """Lightweight markdown-ish cues for streamed prose (no full parser)."""
        stripped = line.lstrip()
        if stripped.startswith("### "):
            return "kite.highlight bold", stripped[4:]
        if stripped.startswith("## "):
            return "kite.highlight bold", stripped[3:]
        if stripped.startswith("# "):
            return "kite.highlight bold", stripped[2:]
        if stripped.startswith(("- ", "* ")):
            indent = line[: len(line) - len(stripped)]
            return "kite.answer", f"{indent}• {stripped[2:]}"
        return "kite.answer", line

    def _thinking_text(self) -> str:
        return "".join(self._thinking_buf)

    def _finalize_thinking(self) -> None:
        text = self._thinking_text().strip()
        if not text:
            self._thinking_buf.clear()
            self._thinking_open = False
            return
        from kite.ui.output_view import format_thinking_text

        view = format_thinking_text(text).rstrip()
        self.state.last_thinking = view or text
        lines = len([ln for ln in self.state.last_thinking.splitlines() if ln.strip()]) or 1
        chars = len(self.state.last_thinking)
        if self.state.thinking_expanded:
            self._stream_write(self.state.last_thinking, channel="thinking")
            self._end_stream_line()
        else:
            self._print(render_thinking_summary(chars, lines), highlight=False)
        self._thinking_buf.clear()
        self._thinking_open = False

    def _append_thinking(self, text: str) -> None:
        if not text:
            return
        self._thinking_buf.append(text)
        self.state.last_thinking = self._thinking_text()
        if self.state.thinking_expanded:
            if not self._thinking_open:
                self._print(Text("Thinking", style="kite.thinking bold"))
                self._thinking_open = True
            self._coalesced_stream("thinking", text)
            return
        chars = len(self.state.last_thinking)
        if not self._thinking_open:
            self._print(Text("Thinking", style="kite.thinking bold"))
            self._thinking_open = True
        self._spin(True, f"thinking  {chars:,} chars")

    def _flush_stream_buffers(self) -> None:
        for channel, chunk in self._stream_coalesce.flush().items():
            if chunk:
                self._stream_write(chunk, channel=channel)

    def _flush_tool_preview(self) -> None:
        if not self._pending_tool_name:
            return
        self._print(
            render_stream_tool_preview(self._pending_tool_name, self._pending_tool_args)
        )
        self._pending_tool_name = None
        self._pending_tool_args = ""

    def _coalesced_stream(self, channel: str, text: str) -> None:
        chunk = self._stream_coalesce.push(channel, text)
        if chunk:
            self.state.note_stream_delta(chunk)
            self._spin(False)
            self._stream_write(chunk, channel=channel)


    def _spin(self, on: bool, label: str = "thinking") -> None:
        if on and not self.quiet:
            self._anim_tick += 1
            if _composer_owns_bottom(self.state):
                if self._spinner_on:
                    self._spinner.stop()
                    self._spinner_on = False
                self.state.set_running(label=label, kind="model")
                return
            fast = label.startswith(("working", "subagent", "preparing"))
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
        self._flush_stream_buffers()
        self._flush_tool_preview()
        self._end_stream_line()

    def print_status(self) -> None:
        """Scroll-print the status line — skipped when the live footer owns it."""
        if self.quiet or self.composer_owns_input:
            return
        self._print(render_status(self.state), highlight=False)

    def print_plan(self) -> None:
        if self.quiet or not self.state.todos:
            return
        key = "|".join(f"{t.id}:{t.status}:{t.content}" for t in self.state.todos)
        if key == self._last_todo_key:
            return
        self._last_todo_key = key
        self._print()
        self._print(render_plan_tasks(self.state.todos, tick=self._anim_tick))

    def print_user_turn(self, task: str) -> None:
        """Persist one user-authored turn — called at submit time, not from events."""
        if self.quiet or not task.strip():
            return
        self._print(render_user_cell(task), highlight=False)

    def __call__(self, event: Event) -> None:
        if self.quiet:
            return
        handler = self._event_handlers.get(event.kind)
        if handler is not None:
            handler(event.payload)

    def _on_attach(self, p: dict[str, Any]) -> None:
        name = str(p.get("name") or "")
        source = str(p.get("source") or "file")
        kind_label = str(p.get("kind") or "")
        extra = f"  {kind_label}" if kind_label and kind_label != "text" else ""
        # Filenames are user text — Text avoids MarkupError on "[...]" paths.
        self._print(
            Text(f"attach  {source}  {name}{extra}", style="kite.muted"),
            highlight=False,
            markup=False,
        )

    def _on_route(self, p: dict[str, Any]) -> None:
        reason = str(p.get("reason") or "")
        if reason == "vision":
            self._print(
                f"[kite.muted]vision  {p.get('provider')}/{p.get('model')}[/]"
            )
        else:
            self._print("[kite.muted]no vision model configured — image noted but not sent[/]")

    def _on_agent_start(self, p: dict[str, Any]) -> None:
        self.state.provider = str(p.get("provider") or self.state.provider)
        self.state.model = str(p.get("model") or self.state.model)
        self.state.interrupted = False
        self._thinking_open = False
        self._thinking_buf.clear()
        if not self.composer_owns_input:
            self.print_user_turn(str(p.get("task") or "").strip())
        self.print_plan()
        self._channel = None
        self._saw_answer = False
        self._streamed_answer = False
        self._deferred_answer_parts.clear()
        self._deferred_agent_end = None
        self._run_tools = 0
        self._run_t0 = time.monotonic()
        self._spin(True, "thinking")

    def _on_stream_start(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self.state.retry_until = None
        self.state.retry_label = ""
        self.state.reset_stream_stats()
        self.state.provider = str(p.get("provider") or self.state.provider)
        self._channel = None
        self._streaming = False
        self._spin(True, "thinking")

    def _on_stream_first_token(self, p: dict[str, Any]) -> None:
        ttft = int(p.get("ttft_ms") or 0)
        channel = str(p.get("channel") or "answer")
        self.state.note_stream_first_token(ttft)
        label = "streaming" if channel == "answer" else f"streaming  {channel}"
        if ttft > 0:
            label = f"{label}  {ttft}ms"
        self._spin(True, label)

    def _on_stream_usage(self, p: dict[str, Any]) -> None:
        self.state.note_stream_usage(dict(p))

    def _on_stream_reasoning(self, p: dict[str, Any]) -> None:
        text = p.get("text") or ""
        if text:
            self._append_thinking(str(text))
        else:
            self._spin(True, "thinking")

    def _on_stream_delta(self, p: dict[str, Any]) -> None:
        text = str(p.get("text") or "")
        if not text:
            self._spin(True, "thinking")
            return
        if self._thinking_buf:
            self._finalize_thinking()
        if self.composer_owns_input:
            # The busy prompt is erased on exit. Keep answer text out of those
            # temporary rows and commit one canonical copy after teardown.
            self._deferred_answer_parts.append(text)
            self.state.note_stream_delta(text)
            return
        self._coalesced_stream("answer", text)

    def _on_stream_tool(self, p: dict[str, Any]) -> None:
        name = str(p.get("name") or "?")
        partial = str(p.get("partial_args") or "")
        phase = str(p.get("phase") or "")
        self._pending_tool_name = name
        self._pending_tool_args = partial
        preview = format_partial_args(partial[-120:] if partial else "", limit=48)
        spin_bits = [f"preparing  {name}"]
        if phase == "name" and name:
            spin_bits.append(name)
        elif preview:
            spin_bits.append(preview)
        self._spin(True, "  ".join(spin_bits))

    def _on_stream_end(self, p: dict[str, Any]) -> None:
        self._flush_stream_buffers()
        self._flush_tool_preview()
        if self._thinking_buf:
            self._finalize_thinking()
        self._end_stream_line()
        self._channel = None
        self._spin(True, "working")

    def _on_turn_start(self, p: dict[str, Any]) -> None:
        self.state.turn += 1
        self._touch_state()

    def _on_turn_end(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(True, "thinking")
        self._touch_state()
        if self.verbose and int(p.get("tools") or 0) > 0:
            meter = render_run_meter(
                tools=int(p.get("tools") or 0),
                duration_ms=p.get("duration_ms"),
                cost=p.get("cost"),
                n_calls=int(p.get("n_calls") or 0),
            )
            if meter is not None:
                self._print(meter)

    def _on_tool_start(self, p: dict[str, Any]) -> None:
        self._flush_stream_buffers()
        self._flush_tool_preview()
        self._end_stream_line()
        tool = str(p.get("tool") or "?")
        args = p.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        reason = str(args.get("reason") or p.get("reason") or "")
        batch = int(p.get("parallel_batch") or 0)
        pindex = int(p.get("parallel_index") or 1)
        if self._saw_answer:
            self._print(render_section_break("tools"), highlight=False)
            self._saw_answer = False
        if batch > 1 and batch != self._parallel_batch:
            self._parallel_batch = batch
            tools = p.get("parallel_tools")
            names = tools if isinstance(tools, list) else []
            self._print(render_parallel_batch_header(batch, names))
        card = ToolCard(
            tool=tool,
            detail=detail_from_args(tool, args),
            reason=reason,
            parallel_batch=max(batch, 1),
            parallel_index=max(pindex, 1),
        )
        detail = card.detail
        if tool == "bash" and args.get("command"):
            detail = str(args["command"]).replace("\n", " ").strip()[:72]
        elif not detail:
            detail = tool
        self.state.set_running(label=detail, kind=tool)
        self.state.touch(force=True)
        quiet = tool in _QUIET_START_TOOLS and not self.verbose
        sub_prefix = _subagent_prefix(p)
        if sub_prefix and self.state.live_subagents:
            self._print(
                Text(f"{GUTTER}{sub_prefix}{tool}", style="kite.plan")
            )
        if not quiet:
            self._print(render_tool_card_start(card))
            if reason:
                self._print(Text(f"{GUTTER}{GUTTER}{reason}", style="kite.muted italic"))
            if tool == "bash" and args.get("command"):
                self._print(render_bash_command_block(str(args["command"])))
            elif tool in {"write", "edit"}:
                preview = render_code_edit_preview(tool, args)
                if preview is not None:
                    self._print(preview)
        self._spin(True, f"working  {tool}")

    def _on_tool_progress(self, p: dict[str, Any]) -> None:
        tool = str(p.get("tool") or "?")
        elapsed = int(p.get("elapsed_s") or 0)
        hint = str(p.get("hint") or "")
        if tool == "compact":
            self.state.set_running(label="Auto-compacting context", kind="compact")
            self.state.touch(force=True)
            return
        label = f"working  {tool}  {elapsed}s{hint}"
        self.state.set_running(label=label.strip(), kind=tool)
        self._spin(True, label)

    def _on_tool_output(self, p: dict[str, Any]) -> None:
        from kite.env.shell import sanitize_shell_line
        from kite.guardrails.redact import redact_string

        line = redact_string(sanitize_shell_line(str(p.get("line") or "")))
        if not line:
            return
        self.state.set_activity_preview(line)
        if not _live_stream_enabled(self.state, p):
            return
        prefix = _subagent_prefix(p)
        self._print(
            Text(f"{prefix}{line}", style="kite.terminal"),
            highlight=False,
        )

    def _on_job_output(self, p: dict[str, Any]) -> None:
        from kite.env.shell import sanitize_shell_line
        from kite.guardrails.redact import redact_string

        line = redact_string(sanitize_shell_line(str(p.get("line") or "")))
        if not line:
            return
        self.state.set_activity_preview(line)
        if not _live_stream_enabled(self.state, p):
            return
        job_id = str(p.get("id") or "")
        prefix = _subagent_prefix(p) or (f"[{job_id}] " if job_id else "")
        self._print(
            Text(f"{prefix}{line}", style="kite.terminal"),
            highlight=False,
        )

    def _on_tool_end(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        self._parallel_batch = 0
        self._run_tools += 1
        tool = str(p.get("tool") or "tool")
        ok = p.get("ok", True)
        blocked = bool(p.get("blocked"))
        structured = p.get("structured") if isinstance(p.get("structured"), dict) else {}
        exit_code = structured.get("exit_code", p.get("exit_code"))
        meta = _tool_meta(p.get("duration_ms"), exit_code)
        diff = p.get("diff")
        preview = str(p.get("preview") or structured.get("preview") or "")
        summary = str(p.get("summary") or "")
        added = deleted = None
        if isinstance(diff, str) and diff.strip():
            counted = count_diff_lines(diff)
            if counted[0] or counted[1]:
                added, deleted = counted
        self._print(
            render_tool_card_done(
                tool,
                ok=ok,
                warn=blocked,
                meta=meta,
                added=added,
                deleted=deleted,
                preview=preview,
                summary=summary,
            )
        )
        output = str(p.get("output") or "")
        summary_line = render_tool_summary(
            preview=preview,
            summary=summary,
            line_count=line_count_from_output(output) if tool == "read" else None,
        )
        if summary_line is not None and (added is None and deleted is None):
            self._print(summary_line)

        if isinstance(diff, str) and diff.strip():

            self._print(render_diff(diff, collapsed=not (self.verbose or self.state.expanded_all)))
        elif not ok:
            err = str(p.get("error") or p.get("output") or "")
            if err:
                expanded = self.verbose or self.state.expanded_all
                collapsed = _collapse_text(err, expanded=expanded)
                if collapsed.plain:
                    self._print(collapsed)
                else:
                    self._print(render_error(err.splitlines()[0], show_trace_hint=False))
        else:
            redacted = p.get("secrets_redacted")
            expanded = self.verbose or self.state.expanded_all
            collapsed = _collapse_text(output, expanded=expanded)
            if collapsed.plain:
                self._print(collapsed)
            if redacted:
                self._print(Text(f"{GUTTER}{GUTTER}· {redacted} secret(s) hidden", style="kite.muted"))

    def _on_artifact(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        status = str(p.get("status") or "unknown")
        if status == "idle" or (
            status == "unverified"
            and not p.get("artifact_count")
            and not p.get("diff_count")
        ):
            return
        style = "kite.success" if status == "verified" else ("kite.pending" if status == "partial" else "kite.error")
        line = Text()
        line.append(f"{SYMBOL_OK if status == 'verified' else SYMBOL_WARN} ", style=style)
        line.append(f"artifacts  {status}", style=style)
        count = p.get("artifact_count")
        if count:
            line.append(f"  ({count})", style="kite.muted")
        self._print(line)
        for art in (p.get("artifacts") or [])[-5:]:
            if isinstance(art, dict):
                mark = SYMBOL_OK if art.get("ok", True) else SYMBOL_FAIL
                self._print(
                    Text(f"{GUTTER}{mark} [{art.get('kind', '?')}] {art.get('summary', '')}", style="kite.muted")
                )
        for gap in p.get("gaps") or []:
            self._print(Text(f"{GUTTER}{SYMBOL_WARN} {gap}", style="kite.pending"))

    def _on_cost_estimate(self, p: dict[str, Any]) -> None:
        try:
            limit = float(p.get("cost_limit") or 0)
        except (TypeError, ValueError):
            limit = 0.0
        if limit > 0:
            self.state.budget_limit = limit
            self._touch_state()
        if _composer_suppresses_scrollprint(self.state):
            return
        note = str(p.get("note") or "")
        if note:
            self._print(Text(f"{GUTTER}{note}", style="kite.muted"))

    def _on_cost_warning(self, p: dict[str, Any]) -> None:
        msg = str(p.get("message") or "cost warning")
        ratio = p.get("ratio") or p.get("pct")
        flash = msg
        if ratio is not None:
            try:
                pct = max(0.0, min(1.0, float(ratio)))
                flash = f"{msg} ({pct:.0%})"
            except (TypeError, ValueError):
                pass
        if self.state.busy:
            self.state.set_flash(flash)
            self._touch_state()
            return
        line = Text()
        line.append(f"{SYMBOL_WARN} ", style="kite.pending")
        line.append(msg, style="kite.pending")
        if ratio is not None:
            try:
                pct = max(0.0, min(1.0, float(ratio)))
                filled = int(round(pct * 10))
                from kite.ui.theme import glyph

                bar = glyph("bar_fill") * filled + glyph("bar_empty") * (10 - filled)
                line.append(f"  {bar} {pct:.0%}", style="kite.muted")
            except (TypeError, ValueError):
                pass
        line.append("\n")
        self._print(line)

    def _on_loop_warning(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        self._print(render_loop_warning(str(p.get("message") or "")))

    def _on_todo(self, p: dict[str, Any]) -> None:
        self.state.set_todos(p.get("items") or [])
        self.print_plan()

    def _on_diff(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        diff = str(p.get("diff") or "")
        path = str(p.get("path") or "")
        if path:
            self._print(Text(f"{GUTTER}{path}", style="kite.muted"))
        if diff:
            self._print(
                render_diff(diff, collapsed=not (self.verbose or self.state.expanded_all))
            )

    def _on_context(self, p: dict[str, Any]) -> None:
        total = p.get("total_tokens")
        window = p.get("window")
        if isinstance(total, int) and isinstance(window, int):
            self.state.set_context_usage(total_tokens=total, window=window)
        elif isinstance(total, int):
            self.state.tokens = total
            self._touch_state()
        elif isinstance(window, int):
            self.state.window = window
            self._touch_state()
        if self.verbose:
            ratio = p.get("ratio")
            bits = [f"ctx {total}/{window}"]
            if ratio is not None:
                bits.append(f"{ratio:.0%}" if isinstance(ratio, float) else str(ratio))
            self._print(f"[kite.muted]{SYMBOL_SEP} {' '.join(str(b) for b in bits)}[/]")

    def _on_compact(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        total = p.get("total_tokens")
        window = p.get("window")
        context_pct: float | None = None
        if isinstance(total, int) and isinstance(window, int) and window > 0:
            self.state.set_context_usage(total_tokens=total, window=window)
            context_pct = min(1.0, total / window)
        self._print(
            render_compact_boundary(
                p.get("before", "?"),
                p.get("after", "?"),
                context_pct=context_pct,
            )
        )

    def _on_compaction_start(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        self.state.compacting = True
        total = p.get("total_tokens")
        window = p.get("window")
        ratio = p.get("ratio")
        self.state.set_running(label="Auto-compacting context", kind="compact")
        line = Text()
        line.append(f"{GUTTER}{SYMBOL_COMPACT}  ", style="kite.muted")
        line.append("compacting context", style="kite.muted bold")
        if isinstance(total, int) and isinstance(window, int):
            line.append(f"  ·  {total:,}/{window:,} tok", style="kite.muted")
        elif ratio is not None:
            line.append(f"  ·  {float(ratio):.0%}", style="kite.muted")
        line.append("\n")
        self._print(line)

    def _on_compaction_end(self, p: dict[str, Any]) -> None:
        self.state.compacting = False
        if not p.get("compacted"):
            if self.state.running_kind == "compact":
                self.state.clear_running()
        total = p.get("total_tokens")
        window = p.get("window")
        if isinstance(total, int) and isinstance(window, int):
            self.state.set_context_usage(total_tokens=total, window=window)

    def _on_checkpoint(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        line = Text()
        line.append(f"{GUTTER}◇ checkpoint  ", style="kite.muted")
        line.append(str(p.get("label", "")), style="kite.muted")
        line.append(f"  {p.get('id', '')}  ", style="kite.terminal")
        line.append(f"({p.get('tokens', '?')} tok)", style="kite.muted")
        line.append("\n")
        self._print(line)

    def _on_commit(self, p: dict[str, Any]) -> None:
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
        self._print(line)

    def _on_interrupt(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        self.state.interrupted = True
        self._print(f"[kite.error]{SYMBOL_FAIL} stopped[/] [kite.muted]— steer with a follow-up to continue[/]")

    def _on_provider_retry(self, p: dict[str, Any]) -> None:
        import time

        self._end_stream_line()
        delay = float(p.get("delay_s") or 0)
        attempt = p.get("attempt")
        max_attempts = p.get("max_attempts")
        self.state.retry_until = time.monotonic() + max(0.0, delay)
        self.state.retry_label = f"{attempt}/{max_attempts}"
        self.state.set_running(label=f"retry {attempt}/{max_attempts}", kind="retry")
        line = Text()
        line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
        line.append(
            f"provider retry {attempt}/{max_attempts} in {delay:.0f}s",
            style="kite.pending bold",
        )
        err = str(p.get("error") or "").strip()
        if err:
            line.append(f"  ·  {err[:100]}", style="kite.muted")
        line.append("\n")
        self._print(line)

    def _on_provider_fault(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        line = Text()
        line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
        line.append("provider unavailable", style="kite.pending bold")
        err = str(p.get("error") or "").strip()
        if err:
            line.append(f"  ·  {err[:120]}", style="kite.muted")
        line.append("\n")
        line.append(f"{GUTTER}{SYMBOL_OK} ", style="kite.success")
        line.append("session saved — send another message to continue", style="kite.success")
        if self.state.provider and self.state.model:
            line.append(f"  ·  {self.state.provider}/{self.state.model}", style="kite.muted")
        line.append("\n")
        self._print(line)

    def _on_approval(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        tool = str(p.get("tool") or "?")
        mandatory = bool(p.get("mandatory"))
        line = Text()
        line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
        line.append("waiting for approval", style="kite.pending bold")
        line.append(f"  ·  {tool}", style="kite.tool")
        if mandatory:
            line.append("  ·  mandatory", style="kite.error")
        line.append("\n")
        self._print(line)

    def _on_submit_blocked(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        reason = str(p.get("reason") or "submit blocked").strip()
        line = Text()
        line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
        line.append("submit blocked", style="kite.pending bold")
        line.append(f"  ·  {reason[:160]}", style="kite.muted")
        line.append("\n")
        self._print(line)
        self.state.set_flash("submit blocked — run verification")
        self._touch_state()

    def _on_verification_status(self, p: dict[str, Any]) -> None:
        status = str(p.get("status") or "").strip()
        if status:
            self.state.verification_status = status
            if status in {"failed", "changed_unverified", "blocked"}:
                self.state.set_flash(f"verification: {status}")
            self._touch_state()

    def _render_agent_end_status(self, p: dict[str, Any]) -> None:
        status = p.get("exit_status") or "done"
        submission = (p.get("submission") or p.get("content") or "").strip()
        if status == "Submitted":
            if submission and not self._streamed_answer:
                self._stream_write(submission, channel="answer")
                self._end_stream_line()
            vstatus = p.get("verification_status")
            vsum = p.get("verification") if isinstance(p.get("verification"), dict) else {}
            had_work = bool(vsum.get("artifact_count") or vsum.get("diff_count") or vsum.get("gaps"))
            if vstatus in {"failed", "partial"} or (vstatus == "unverified" and had_work):
                self._print(
                    Text(
                        f"{SYMBOL_WARN} couldn't fully verify — status: {vstatus}. Check the artifacts above.",
                        style="kite.pending",
                    )
                )
            return
        if status in {"Interrupted", "Denied"}:
            self._print(Text(str(status).lower(), style="kite.pending"))
            return
        if status == "ProviderFault":
            err = str(p.get("error") or "provider error")
            line = Text()
            line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
            line.append("paused — provider fault", style="kite.pending")
            line.append(f"  ·  {err[:100]}", style="kite.muted")
            line.append("\n")
            self._print(line)
            return
        if status == "Stalled":
            msg = str(p.get("submission") or p.get("content") or "stopped — no progress")
            self._print(render_error(msg, show_trace_hint=False))
            return
        if status == "Error":
            err = str(p.get("error") or "unexpected error")
            trace = str(p.get("traceback") or "")
            self.state.last_error = err
            self.state.last_trace = trace
            self._print(render_error(err, traceback_text=trace))
            return
        if status == "RepeatedFormatError":
            detail = str(p.get("submission") or p.get("content") or status)
            self._print(render_error(f"{status}: {detail}", show_trace_hint=False))
            return
        if status in {"LimitsExceeded", "TimeExceeded"}:
            detail = str(p.get("submission") or p.get("content") or "").strip()
            if detail.lower() in {"", status.lower()}:
                detail = "step or cost budget reached" if status == "LimitsExceeded" else "wall-clock limit reached"
            label = "paused — budget reached" if status == "LimitsExceeded" else "paused — time limit"
            line = Text()
            line.append(f"{GUTTER}{SYMBOL_WARN} ", style="kite.pending")
            line.append(label, style="kite.pending bold")
            line.append(f"  ·  {detail[:120]}", style="kite.muted")
            line.append("\n")
            line.append(f"{GUTTER}{SYMBOL_OK} ", style="kite.success")
            line.append("session saved — send another message to continue", style="kite.success")
            line.append("\n")
            self._print(line)
            return
        self._print(render_error(str(status), show_trace_hint=False))

    def _on_agent_end(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        self.state.budget_limit = None
        self.state.clear_running()
        self._touch_state()
        if self.composer_owns_input:
            self._deferred_agent_end = dict(p)
            return
        self._render_agent_end_status(p)
        self._print_run_meter(p)
        self.print_status()

    def finish_composer_turn(self, result: dict[str, Any] | None = None) -> None:
        """Commit the final answer after prompt_toolkit has erased the busy UI."""
        payload = self._deferred_agent_end or dict(result or {})
        self._deferred_agent_end = None
        if not payload:
            self._deferred_answer_parts.clear()
            return
        submission = str(payload.get("submission") or payload.get("content") or "").strip()
        streamed = "".join(self._deferred_answer_parts).strip()
        if submission and streamed and str(payload.get("exit_status") or "Submitted") == "Submitted":
            if submission in streamed or streamed in submission:
                answer = max(submission, streamed, key=len)
            else:
                vsum = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
                had_work = bool(vsum.get("artifact_count") or vsum.get("diff_count"))
                if _looks_like_turn_report(submission) and not had_work:
                    answer = streamed
                else:
                    answer = f"{streamed}\n\n{submission}"
        else:
            answer = submission or streamed
        if answer and str(payload.get("exit_status") or "Submitted") == "Submitted":
            self._streamed_answer = False
            self._stream_write(answer, channel="answer")
            self._end_stream_line()
        self._render_agent_end_status(payload)
        self._print_run_meter(payload)

    def _print_run_meter(self, p: dict[str, Any]) -> None:
        tools = int(p.get("tools") or self._run_tools or 0)
        duration = p.get("duration_ms")
        if duration is None and self._run_t0 is not None:
            duration = int((time.monotonic() - self._run_t0) * 1000)
        try:
            cost = float(p.get("cost") if p.get("cost") is not None else self.state.cost)
        except (TypeError, ValueError):
            cost = self.state.cost
        meter = render_run_meter(
            tools=tools,
            duration_ms=int(duration) if duration is not None else None,
            cost=cost,
            tokens=int(self.state.tokens or 0),
            n_calls=int(p.get("n_calls") or self.state.n_calls or 0),
        )
        if meter is not None:
            self._print(meter)

    def _on_error(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        self._spin(False)
        msg = str(p.get("error") or "error")
        self.state.last_error = msg
        self.state.last_trace = str(p.get("traceback") or "")
        self._print(
            render_error(msg, traceback_text=self.state.last_trace, show_trace_hint=not self.state.last_trace)
        )

    def _on_cost(self, p: dict[str, Any]) -> None:
        try:
            self.state.cost = float(p.get("cost") or self.state.cost)
        except (TypeError, ValueError):
            pass
        usage = p.get("usage") if isinstance(p.get("usage"), dict) else None
        self.state.apply_usage(usage)
        self._touch_state()

    def _on_cache_hit(self, p: dict[str, Any]) -> None:
        session = p.get("session") if isinstance(p.get("session"), dict) else {}
        self.state.apply_usage(p, session=session)
        hits = int(session.get("cache_hit_tokens") or p.get("cache_read") or p.get("cached") or 0)
        if hits:
            self.state.cache_hit_tokens = hits
            try:
                self.state.cache_hit_ratio = float(session.get("hit_ratio") or p.get("hit_ratio") or 0.0)
            except (TypeError, ValueError):
                pass
            self._touch_state()
            if self.verbose:
                self._print(
                    f"[kite.muted]{GUTTER}cache hit  {hits} tokens ({self.state.cache_hit_ratio:.0%})[/]"
                )

    def _on_orchestrator_start(self, p: dict[str, Any]) -> None:
        total = int(p.get("total") or 0)
        workers = int(p.get("workers") or total)
        if total <= 1:
            return
        self._end_stream_line()
        at_once = f" · {workers} at a time" if workers < total else ""
        self._print(
            Text(
                f"{GUTTER}{SYMBOL_COLLAPSE} crew  {total} workers{at_once}",
                style="kite.plan bold",
            )
        )

    def _on_orchestrator_end(self, p: dict[str, Any]) -> None:
        total = int(p.get("total") or 0)
        succeeded = int(p.get("succeeded") or p.get("delivered") or 0)
        if total <= 1:
            return
        ok = bool(p.get("ok"))
        mark = SYMBOL_OK if ok else SYMBOL_WARN
        style = "kite.success" if ok else "kite.muted"
        self._print(
            Text(
                f"{GUTTER}{mark} crew  {succeeded}/{total} succeeded",
                style=style,
            )
        )
        self._render_subagent_board(p.get("manager"))

    def _render_subagent_board(self, manager: Any) -> None:
        if not isinstance(manager, list) or not manager:
            return
        from kite.ui.tables import kite_table

        table = kite_table()
        table.add_column("", width=2)
        table.add_column("worker", style="kite.plan")
        table.add_column("status")
        table.add_column("ms", justify="right")
        for row in manager[-6:]:
            if not isinstance(row, dict):
                continue
            glyph = str(row.get("glyph") or "◆")
            label = str(row.get("label") or row.get("id") or "worker")
            quality = str(row.get("quality") or row.get("status") or "")
            elapsed = row.get("elapsed_ms")
            timing = str(elapsed) if elapsed else "—"
            table.add_row(glyph, label[:28], quality, timing)
        self._print(table)

    def _on_subagent_start(self, p: dict[str, Any]) -> None:
        self._end_stream_line()
        label = str(p.get("label") or p.get("id") or "subagent")
        glyph = str(p.get("glyph") or "◆")
        profile = str(p.get("profile") or "")
        self.state.active_subagents += 1
        self._touch_state()
        suffix = f"  ·  {profile}" if profile else ""
        self._print(
            Text(f"{GUTTER}{SYMBOL_COLLAPSE} {glyph}  {label}{suffix}", style="kite.plan")
        )
        if self.state.live_subagents:
            from kite.guardrails.redact import redact_string

            prompt = redact_string(str(p.get("prompt") or "")[:120])
            if prompt:
                self._print(Text(f"{GUTTER}{GUTTER}{prompt}", style="kite.muted"))
        self._spin(True, f"{glyph}  {label}")

    def _on_subagent_end(self, p: dict[str, Any]) -> None:
        self._spin(False)
        label = str(p.get("label") or p.get("id") or "subagent")
        glyph = str(p.get("glyph") or "◆")
        ok = p.get("ok", True)
        quality = str(p.get("quality") or ("done" if ok else "failed"))
        mark = SYMBOL_OK if ok else SYMBOL_FAIL
        style = "kite.success" if ok else ("kite.muted" if quality == "partial" else "kite.error")
        self.state.active_subagents = max(0, self.state.active_subagents - 1)
        self._touch_state()
        elapsed = p.get("elapsed_ms")
        timing = f"  ·  {elapsed}ms" if elapsed else ""
        detail = f"  ·  {quality}" if quality not in {"done", "failed"} else ""
        self._print(
            Text(f"{GUTTER}{mark} {glyph}  {label}{detail}{timing}", style=style)
        )
        preview = str(p.get("preview") or "")
        if preview:
            from kite.guardrails.redact import redact_string

            self._print(
                Text(f"{GUTTER}{GUTTER}{redact_string(preview[:100])}", style="kite.muted")
            )

    def _on_job_start(self, p: dict[str, Any]) -> None:
        try:
            active = int(p.get("active") or 0)
            self.state.active_jobs = active if active else self.state.active_jobs + 1
        except (TypeError, ValueError):
            self.state.active_jobs += 1
        self._touch_state()
        kind = str(p.get("kind") or "job")
        if kind == "subagent":
            return
        label = str(p.get("label") or p.get("command") or p.get("id") or "job")
        if kind == "bash":
            self._print(
                Text(f"{GUTTER}{SYMBOL_COLLAPSE} job  {kind}  {label}", style="kite.muted")
            )

    def _on_job_end(self, p: dict[str, Any]) -> None:
        try:
            if "active" in p:
                self.state.active_jobs = max(0, int(p.get("active") or 0))
            else:
                self.state.active_jobs = max(0, self.state.active_jobs - 1)
        except (TypeError, ValueError):
            self.state.active_jobs = max(0, self.state.active_jobs - 1)
        self._touch_state()
        kind = str(p.get("kind") or "")
        if kind == "subagent":
            return
        ok = p.get("ok", True)
        mark = SYMBOL_OK if ok else SYMBOL_FAIL
        style = "kite.success" if ok else "kite.muted"
        label = str(p.get("label") or p.get("id") or "job")
        status = str(p.get("status") or ("done" if ok else "ended"))
        if kind == "bash":
            self._print(Text(f"{GUTTER}{mark} job  {kind}  {label}  {status}", style=style))

    def _on_warning(self, p: dict[str, Any]) -> None:
        msg = str(p.get("message") or "").strip()
        if msg:
            self._print(Text(f"{GUTTER}{SYMBOL_WARN} {msg}", style="kite.muted"))

    def _on_mode(self, p: dict[str, Any]) -> None:
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

def make_run_display(
    console: Console,
    *,
    quiet: bool,
    verbose: bool,
    state: SessionUiState | None = None,
) -> RunDisplay:
    return RunDisplay(console, quiet=quiet, verbose=verbose, state=state)
