"""Session UI state — single source of truth for the TUI."""

from __future__ import annotations

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
    reasoning: str = "auto"
    pending_attach: int = 0

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
