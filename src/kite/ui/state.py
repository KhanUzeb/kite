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
    thinking_expanded: bool = True  # stream full thinking by default; Ctrl+T toggles
    last_thinking: str = ""
    reasoning: str = "auto"
    pending_attach: int = 0
    cache_hit_tokens: int = 0
    cache_hit_ratio: float = 0.0
    stream_chars: int = 0
    stream_started_at: float | None = None
    tps: float = 0.0
    active_subagents: int = 0
    active_jobs: int = 0
    turn: int = 0
    sandbox_restricted: bool = False  # False = host (default); True = restricted sandbox
    flash: str = ""
    verification_status: str = ""
    busy: bool = False
    awaiting_approval: str = ""
    queued: int = 0
    running_label: str = ""
    running_since: str = ""
    running_kind: str = ""
    budget_limit: float | None = None  # turn cost ceiling; toolbar chip while busy
    _refresh: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def touch(self) -> None:
        """Notify live composer toolbar (prompt_toolkit) to redraw."""
        if self._refresh:
            self._refresh()

    def set_running(self, *, label: str, kind: str = "tool") -> None:
        from datetime import datetime

        self.running_label = label.strip()
        self.running_kind = kind
        self.running_since = datetime.now().strftime("%H:%M:%S")
        self.touch()

    def clear_running(self) -> None:
        self.running_label = ""
        self.running_since = ""
        self.running_kind = ""
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
        self.touch()

    def set_context_usage(self, *, total_tokens: int, window: int) -> None:
        """Update ctx meter from a compaction measure or estimate."""
        self.tokens = total_tokens
        self.window = window
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
            out.append(
                TodoItem(
                    id=str(raw.get("id") or i),
                    content=str(raw.get("content") or raw.get("text") or ""),
                    status=raw.get("status") or "pending",  # type: ignore[arg-type]
                )
            )
        self.todos = out
