"""Session UI state — single source of truth for the TUI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from kite.agent.mode import AgentMode, ApprovalMode

TodoStatus = Literal["pending", "in_progress", "completed"]

# One TTL for the read-path and the touch-path check so the two cannot drift.
_FLASH_TTL_S = 8.0


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
    approval: ApprovalMode = ApprovalMode.AUTO
    provider: str = ""
    model: str = ""
    git_branch: str = ""
    git_dirty: int = -1
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
    expanded_all: bool = True
    live_terminal: bool = True
    live_subagents: bool = True
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
    stream_tokens: int = 0
    stream_started_at: float | None = None
    ttft_ms: int | None = None
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
        min_interval = 0.15 if self.busy else 0.125
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
        # Forced: a flash is a one-shot notification, not a stream sample. At
        # the prompt the repaint throttle can swallow it — nothing drains
        # _touch_pending while idle — so the footer would never show it.
        self.touch(force=True)

    def maybe_clear_flash(self, ttl: float = _FLASH_TTL_S) -> None:
        if not self.flash or self.flash_at is None:
            return
        import time

        if time.monotonic() - self.flash_at > ttl:
            self.flash = ""
            self.flash_at = None

    @property
    def active_flash(self, ttl: float = _FLASH_TTL_S) -> str:
        """Live flash for renderers — expiry checked on read, not just on touch.

        ``touch()`` only runs while something is painting, so a flash set at an
        idle prompt outlived its TTL and stayed on the footer indefinitely. The
        toolbar renders on every keystroke, so checking here expires it the
        moment it is actually looked at.
        """
        self.maybe_clear_flash(ttl)
        return self.flash

    def set_running(self, *, label: str, kind: str = "tool", touch: bool = True) -> None:
        from datetime import datetime

        label = label.strip()
        if self.busy and label == self.running_label and kind == self.running_kind:
            return
        self.running_label = label
        self.running_kind = kind
        self.running_since = datetime.now().strftime("%H:%M:%S")
        if touch:
            self.touch()

    def clear_running(self) -> None:
        self.running_label = ""
        self.running_since = ""
        self.running_kind = ""
        self.activity_preview = ""
        # Forced: this is a turn/idle boundary, not a stream sample. The only
        # flush_pending_touch() call lives in the busy-turn pollers, which have
        # already stopped by the time the boundary runs — a throttled touch
        # here leaves the footer frozen on the last "working" line until the
        # user types something.
        self.touch(force=True)

    def set_activity_preview(self, line: str, *, touch: bool = True) -> None:
        from kite.ui.status import sanitize_status_text

        clean = sanitize_status_text(line)
        if not clean or clean == self.activity_preview:
            return
        self.activity_preview = clean
        if touch:
            self.touch()

    def reset_stream_stats(self) -> None:
        self.stream_chars = 0
        self.stream_tokens = 0
        self.stream_started_at = None
        self.ttft_ms = None
        self.tps = 0.0
        # Forced: cancel/turn boundaries must not drop the footer update
        # to a throttled touch — otherwise reset looks like lost events.
        self.touch(force=True)

    def note_stream_first_token(self, ttft_ms: int) -> None:
        if self.ttft_ms is None and ttft_ms >= 0:
            self.ttft_ms = ttft_ms
            self.touch()

    def note_stream_delta(self, text: str, *, tokens: int | None = None, touch: bool = True) -> None:
        import time

        if not text:
            return
        now = time.monotonic()
        if self.stream_started_at is None:
            self.stream_started_at = now
        self.stream_chars += len(text)
        if tokens is not None and tokens > 0:
            self.stream_tokens += tokens
        elapsed = now - (self.stream_started_at or now)
        if elapsed > 0:
            est = self.stream_tokens if self.stream_tokens > 0 else max(1, self.stream_chars // 4)
            self.tps = est / elapsed
        # Busy turns own the footer via the composer toolbar — without a touch
        # here the running line sits silent through a long generation and reads
        # as frozen. touch() throttles (0.15s busy), so this stays bounded.
        # Callers pass touch=False while the pinned composer owns the bottom:
        # every touch() invalidates the prompt app, and each repaint reclaims
        # the patch_stdout region — erasing the end="" partials just painted.
        # Stats still update; the toolbar picks them up on its own 0.25s poll.
        if touch:
            self.touch()

    def note_stream_usage(self, usage: dict) -> None:
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        if completion > 0:
            self.stream_tokens = max(self.stream_tokens, completion)
            if self.stream_started_at is not None:
                import time

                elapsed = time.monotonic() - self.stream_started_at
                if elapsed > 0:
                    self.tps = self.stream_tokens / elapsed
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
        # Non-positive, not just zero: a misconfigured context_window must read
        # as "unknown" — dividing by it yields ctx -800%, and negative totals
        # would put the meter's fill count below zero.
        if self.window <= 0 or self.tokens < 0:
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
