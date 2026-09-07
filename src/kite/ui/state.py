"""Session UI state — single source of truth for the TUI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from kite.agent.mode import AgentMode, ApprovalMode

TodoStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class TodoItem:
    id: str
    content: str
    status: TodoStatus = "pending"


@dataclass
class ToolBlock:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    output: str = ""
    error: str = ""
    ok: bool | None = None
    collapsed: bool = True
    blocked: bool = False


@dataclass
class SessionUiState:
    mode: AgentMode = AgentMode.BUILD
    approval: ApprovalMode = ApprovalMode.APPROVE
    provider: str = ""
    model: str = ""
    git_branch: str = ""
    cost: float = 0.0
    tokens: int = 0
    window: int = 0
    n_calls: int = 0
    spinner: str = ""
    interrupted: bool = False
    last_error: str = ""
    last_trace: str = ""
    todos: list[TodoItem] = field(default_factory=list)
    last_tool: ToolBlock | None = None
    expanded_all: bool = False
    live_terminal: bool = False
    thinking_expanded: bool = True
    last_thinking: str = ""
    reasoning: str = "auto"
    pending_attach: int = 0
    cache_hit_tokens: int = 0
    cache_hit_ratio: float = 0.0
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    usage_cache_read_tokens: int = 0
    usage_cache_write_tokens: int = 0
    stream_chars: int = 0
    stream_started_at: float | None = None
    tps: float = 0.0
    active_subagents: int = 0
    active_jobs: int = 0
    turn: int = 0
    sandbox_restricted: bool = False
    flash: str = ""
    flash_at: float | None = None
    verification_status: str = ""
    busy: bool = False
    awaiting_approval: str = ""
    awaiting_approval_mandatory: bool = False
    queued: int = 0
    queue_steer: int = 0
    queue_follow: int = 0
    queue_head: str = ""
    queue_head_kind: str = ""
    compacting: bool = False
    retry_until: float | None = None
    retry_label: str = ""
    running_label: str = ""
    running_since: str = ""
    running_kind: str = ""
    activity_preview: str = ""
    budget_limit: float | None = None
    _refresh: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    _last_touch_at: float = field(default=0.0, repr=False, compare=False)
    _touch_pending: bool = field(default=False, repr=False, compare=False)

    def touch(self, *, force: bool = False) -> None:
        self.maybe_clear_flash()
        import time

        now = time.monotonic()
        min_interval = 0.4 if self.busy else 0.125
        if not force and self._refresh and (now - self._last_touch_at) < min_interval:
            self._touch_pending = True
            return
        self._last_touch_at = now
        self._touch_pending = False
        if self._refresh:
            self._refresh()

    def flush_pending_touch(self) -> None:
        if self._touch_pending:
            self.touch(force=True)

    def set_flash(self, text: str) -> None:
        import time

        if text:
            self.flash = text
            self.flash_at = time.monotonic()
        else:
            self.flash = ""
            self.flash_at = None

    def maybe_clear_flash(self, ttl: float = 8.0) -> None:
        if not self.flash or self.flash_at is None:
            return
        import time

        if time.monotonic() - self.flash_at > ttl:
            self.flash = ""
            self.flash_at = None

    def set_running(self, *, label: str, kind: str = "tool") -> None:
        from datetime import datetime

        label = label.strip()
        if self.busy and label == self.running_label and kind == self.running_kind:
            return
        self.running_label = label
        self.running_kind = kind
        self.running_since = datetime.now().strftime("%H:%M:%S")
        self.touch()

    def clear_running(self) -> None:
        self.running_label = ""
        self.running_since = ""
        self.running_kind = ""
        self.activity_preview = ""
        self.touch()

    def set_activity_preview(self, line: str) -> None:
        from kite.ui.status import sanitize_status_text

        clean = sanitize_status_text(line)
        if not clean or clean == self.activity_preview:
            return
        self.activity_preview = clean
        self.touch()

    def reset_stream_stats(self) -> None:
        self.stream_chars = 0
        self.stream_started_at = None
        self.tps = 0.0
        self.touch()

    def note_stream_delta(self, text: str) -> None:
        import time

        if not text:
            return
        now = time.monotonic()
        if self.stream_started_at is None:
            self.stream_started_at = now
        self.stream_chars += len(text)
        elapsed = now - (self.stream_started_at or now)
        if elapsed > 0:
            est_tokens = max(1, self.stream_chars // 4)
            self.tps = est_tokens / elapsed
        if not self.busy:
            self.touch()

    def set_context_usage(self, *, total_tokens: int, window: int) -> None:
        self.tokens = total_tokens
        self.window = window
        self.touch()

    def apply_usage(self, raw: dict[str, Any] | None = None, *, session: dict[str, Any] | None = None) -> None:
        from kite.models.usage import UsageTotals

        totals = UsageTotals(
            input_tokens=self.usage_input_tokens,
            output_tokens=self.usage_output_tokens,
            cache_read_tokens=self.usage_cache_read_tokens,
            cache_write_tokens=self.usage_cache_write_tokens,
            cost=self.cost,
        )
        totals.absorb(raw)
        totals.absorb_session(session)
        self.usage_input_tokens = totals.input_tokens
        self.usage_output_tokens = totals.output_tokens
        self.usage_cache_read_tokens = totals.cache_read_tokens
        self.usage_cache_write_tokens = totals.cache_write_tokens
        if totals.cache_read_tokens or totals.cache_write_tokens:
            self.cache_hit_tokens = totals.cache_read_tokens or self.cache_hit_tokens
            self.cache_hit_ratio = totals.cache_hit_ratio
        self.touch()

    @property
    def context_pct(self) -> float | None:
        if not self.window:
            return None
        return min(1.0, self.tokens / self.window)

    def set_todos(self, items: list[dict[str, Any]] | list[TodoItem]) -> None:
        out: list[TodoItem] = []
        for i, raw in enumerate(items, start=1):
            if isinstance(raw, TodoItem):
                out.append(raw)
                continue
            status_raw = raw.get("status") or "pending"
            status: TodoStatus = (
                status_raw
                if status_raw in {"pending", "in_progress", "completed"}
                else "pending"
            )
            out.append(
                TodoItem(
                    id=str(raw.get("id") or i),
                    content=str(raw.get("content") or raw.get("text") or ""),
                    status=status,
                )
            )
        self.todos = out
