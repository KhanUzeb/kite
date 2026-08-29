"""Shared mutable stores tools write and the UI reads."""

from __future__ import annotations

from typing import Any, Literal

TodoStatus = Literal["pending", "in_progress", "completed"]


class TodoStore:
    """Backing store for todo_write / todo_read — auditable, not client-only UI state."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def write(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, raw in enumerate(items or [], start=1):
            if not isinstance(raw, dict):
                continue
            status = raw.get("status") or "pending"
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            out.append(
                {
                    "id": str(raw.get("id") or i),
                    "content": str(raw.get("content") or raw.get("text") or "").strip(),
                    "status": status,
                }
            )
        self.items = [x for x in out if x["content"]]
        return list(self.items)

    def read(self) -> list[dict[str, Any]]:
        return list(self.items)
