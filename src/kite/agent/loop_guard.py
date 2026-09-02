"""Detect repetitive tool loops and nudge the agent to change strategy."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

BASH_REPEAT_THRESHOLD = 2
DEFAULT_HARD_THRESHOLD = 5


def _tool_signature(tool: str, args: dict[str, Any]) -> str:
    """Stable hash for (tool, arguments) — ignores reason field."""
    payload = {"tool": tool, "args": {k: v for k, v in sorted(args.items()) if k != "reason"}}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _output_fingerprint(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    text = str(result.get("output") or result.get("error") or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class LoopRecord:
    warning: str | None = None
    hard_stop: str | None = None


class LoopGuard:
    """Track recent tool calls; flag when the agent repeats the same action."""

    def __init__(
        self,
        *,
        repeat_threshold: int = 3,
        hard_threshold: int = DEFAULT_HARD_THRESHOLD,
        window: int = 12,
    ) -> None:
        self.repeat_threshold = max(2, repeat_threshold)
        self.hard_threshold = max(self.repeat_threshold + 1, hard_threshold)
        self.window = max(4, window)
        self._recent: deque[str] = deque()
        self._counts: Counter[str] = Counter()
        self._last_output: dict[str, str] = {}

    def record(self, tool: str, args: dict[str, Any], result: dict[str, Any] | None = None) -> LoopRecord:
        """Record a tool call. Returns warnings or hard-stop when stuck in a loop."""
        sig = _tool_signature(tool, args)
        fp = _output_fingerprint(result)
        ok = bool(result.get("ok")) if result else False

        # Progress reset (Cline/OpenHands pattern): different successful output ≠ stuck.
        if ok and fp and self._last_output.get(sig) not in ("", fp):
            self._counts[sig] = 0
        if fp:
            self._last_output[sig] = fp

        self._recent.append(sig)
        self._counts[sig] += 1
        if len(self._recent) > self.window:
            dropped = self._recent.popleft()
            self._counts[dropped] -= 1
            if self._counts[dropped] <= 0:
                del self._counts[dropped]

        count = self._counts[sig]
        soft = BASH_REPEAT_THRESHOLD if tool == "bash" else self.repeat_threshold
        if count < soft:
            return LoopRecord()

        if count >= self.hard_threshold:
            return LoopRecord(
                hard_stop=(
                    f"Loop hard-stop: `{tool}` repeated {count} times with the same arguments. "
                    "Stop retrying. Ask the user, try a different tool/strategy, or submit honestly "
                    "with what you verified and what remains blocked."
                )
            )

        return LoopRecord(
            warning=(
                f"You've run `{tool}` with the same arguments {count} times in a row. "
                "Try a different approach, ask the user a question, or submit what you have "
                "with an honest note about what's left."
            )
        )

    def reset(self) -> None:
        self._recent.clear()
        self._counts.clear()
        self._last_output.clear()
