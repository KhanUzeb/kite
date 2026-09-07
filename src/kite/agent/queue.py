"""Runtime follow-up queue — steer prepends, Enter appends (pi-agent-core style)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RunMessageQueue:
    _items: deque[tuple[str, bool]] = field(default_factory=deque)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        for text, _ in self._items:
            yield text

    def peek(self) -> str:
        return self._items[0][0] if self._items else ""

    def peek_entry(self) -> tuple[str, bool] | None:
        return self._items[0] if self._items else None

    def entries(self) -> list[tuple[str, bool]]:
        return list(self._items)

    def counts(self) -> tuple[int, int]:
        steer = sum(1 for _, is_steer in self._items if is_steer)
        return steer, len(self._items) - steer

    def drain_all(self) -> list[tuple[str, bool]]:
        items = list(self._items)
        self._items.clear()
        return items

    def enqueue(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        self._items.append((text, False))
        return True

    def steer(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        self._items.appendleft((text, True))
        return True

    def dequeue(self) -> str | None:
        if not self._items:
            return None
        return self._items.popleft()[0]

    def has_steer(self) -> bool:
        return bool(self._items) and self._items[0][1]

    def pop_steers(self) -> list[str]:
        out: list[str] = []
        while self._items and self._items[0][1]:
            out.append(self._items.popleft()[0])
        return out

    def drain_followups(self) -> list[str]:
        out: list[str] = []
        while self._items and not self._items[0][1]:
            out.append(self._items.popleft()[0])
        return out
