"""Detect repetitive tool loops and nudge the agent to change strategy."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from typing import Any

BASH_REPEAT_THRESHOLD = 2


def _tool_signature(tool: str, args: dict[str, Any]) -> str:
    """Stable hash for (tool, arguments) — ignores reason field."""
    payload = {"tool": tool, "args": {k: v for k, v in sorted(args.items()) if k != "reason"}}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class LoopGuard:
    """Track recent tool calls; flag when the agent repeats the same action."""

    def __init__(self, *, repeat_threshold: int = 3, window: int = 12) -> None:
        self.repeat_threshold = max(2, repeat_threshold)
        self.window = max(4, window)
        self._recent: deque[str] = deque()
        self._counts: Counter[str] = Counter()

    def record(self, tool: str, args: dict[str, Any]) -> str | None:
        """Record a tool call. Returns a warning message if a loop is detected."""
        sig = _tool_signature(tool, args)
        self._recent.append(sig)
        self._counts[sig] += 1
        if len(self._recent) > self.window:
            dropped = self._recent.popleft()
            self._counts[dropped] -= 1
            if self._counts[dropped] <= 0:
                del self._counts[dropped]

        count = self._counts[sig]
        threshold = BASH_REPEAT_THRESHOLD if tool == "bash" else self.repeat_threshold
        if count < threshold:
            return None

        return (
            f"You've run `{tool}` with the same arguments {count} times in a row. "
            "Try a different approach, ask the user a question, or submit what you have "
            "with an honest note about what's left."
        )

    def reset(self) -> None:
        self._recent.clear()
        self._counts.clear()
