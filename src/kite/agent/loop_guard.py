"""Detect repetitive tool loops and nudge the agent to change strategy."""

from __future__ import annotations

import hashlib
import json
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
        self._recent: list[str] = []

    def record(self, tool: str, args: dict[str, Any]) -> str | None:
        """Record a tool call. Returns a warning message if a loop is detected."""
        sig = _tool_signature(tool, args)
        self._recent.append(sig)
        if len(self._recent) > self.window:
            self._recent = self._recent[-self.window :]

        count = self._recent.count(sig)
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
