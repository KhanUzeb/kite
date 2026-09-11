"""Coalesce streaming text chunks before Rich writes — fewer flickery prints."""

from __future__ import annotations

import time


class StreamCoalescer:
    """Batch small stream_delta / stream_reasoning pieces."""

    def __init__(
        self,
        *,
        min_chars: int = 8,
        flush_chars: int = 128,
        max_latency_s: float = 0.05,
    ) -> None:
        self.min_chars = min_chars
        self.flush_chars = flush_chars
        self.max_latency_s = max(0.0, max_latency_s)
        self._buffers: dict[str, str] = {}
        self._last_push: dict[str, float] = {}

    def push(self, channel: str, text: str) -> str | None:
        if not text:
            return None
        now = time.monotonic()
        buf = self._buffers.get(channel, "") + text
        started = self._last_push.get(channel, now)
        aged = (now - started) >= self.max_latency_s
        if (
            len(buf) >= self.flush_chars
            or ("\n" in text and len(buf) >= self.min_chars)
            or (aged and len(buf) >= self.min_chars)
        ):
            self._buffers[channel] = ""
            self._last_push[channel] = now
            return buf
        self._buffers[channel] = buf
        if channel not in self._last_push:
            self._last_push[channel] = now
        return None

    def flush(self, channel: str | None = None) -> dict[str, str]:
        if channel is not None:
            chunk = self._buffers.pop(channel, "")
            self._last_push.pop(channel, None)
            return {channel: chunk} if chunk else {}
        out = {k: v for k, v in self._buffers.items() if v}
        self._buffers.clear()
        self._last_push.clear()
        return out
