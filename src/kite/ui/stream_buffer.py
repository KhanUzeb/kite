"""Coalesce streaming text chunks before Rich writes — fewer flickery prints."""

from __future__ import annotations


class StreamCoalescer:
    """Batch small stream_delta / stream_reasoning pieces."""

    def __init__(self, *, min_chars: int = 8, flush_chars: int = 128) -> None:
        self.min_chars = min_chars
        self.flush_chars = flush_chars
        self._buffers: dict[str, str] = {}

    def push(self, channel: str, text: str) -> str | None:
        if not text:
            return None
        buf = self._buffers.get(channel, "") + text
        if len(buf) >= self.flush_chars or ("\n" in text and len(buf) >= self.min_chars):
            self._buffers[channel] = ""
            return buf
        self._buffers[channel] = buf
        return None

    def flush(self, channel: str | None = None) -> dict[str, str]:
        if channel is not None:
            chunk = self._buffers.pop(channel, "")
            return {channel: chunk} if chunk else {}
        out = {k: v for k, v in self._buffers.items() if v}
        self._buffers.clear()
        return out
