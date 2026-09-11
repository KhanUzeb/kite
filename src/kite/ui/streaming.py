"""Token stream batching — typed channel projections (text / reasoning / tools).

Inspired by LangChain's ``stream_events(version="v3")`` projections (``.text``,
``.reasoning``, ``.tool_calls``) but implemented natively on Kite's event bus.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

# Sentence / clause boundaries — flush early for snappier perceived latency.
_BOUNDARY_RE = re.compile(r"(?:[.!?][\s\"')\]]*|\n)\s*$")


@dataclass(frozen=True)
class ChannelProfile:
    """Per-channel coalescing — answer streams feel live; thinking batches more."""

    min_chars: int = 4
    flush_chars: int = 96
    max_latency_s: float = 0.04
    flush_on_boundary: bool = True


ANSWER_PROFILE = ChannelProfile(min_chars=1, flush_chars=48, max_latency_s=0.022, flush_on_boundary=True)
THINKING_PROFILE = ChannelProfile(min_chars=8, flush_chars=128, max_latency_s=0.06, flush_on_boundary=False)
DEFAULT_PROFILE = ChannelProfile()

_CHANNEL_PROFILES: dict[str, ChannelProfile] = {
    "answer": ANSWER_PROFILE,
    "thinking": THINKING_PROFILE,
}


def should_flush_on_boundary(text: str, profile: ChannelProfile) -> bool:
    if not profile.flush_on_boundary or not text:
        return False
    return bool(_BOUNDARY_RE.search(text))


class StreamCoalescer:
    """Batch small stream chunks before terminal writes — fewer flickery prints."""

    def __init__(
        self,
        *,
        profiles: dict[str, ChannelProfile] | None = None,
        min_chars: int | None = None,
        flush_chars: int | None = None,
        max_latency_s: float | None = None,
    ) -> None:
        self._profiles = profiles or _CHANNEL_PROFILES
        self._default = DEFAULT_PROFILE
        if min_chars is not None or flush_chars is not None or max_latency_s is not None:
            self._default = ChannelProfile(
                min_chars=min_chars if min_chars is not None else DEFAULT_PROFILE.min_chars,
                flush_chars=flush_chars if flush_chars is not None else DEFAULT_PROFILE.flush_chars,
                max_latency_s=max_latency_s if max_latency_s is not None else DEFAULT_PROFILE.max_latency_s,
            )
        self._buffers: dict[str, str] = {}
        self._last_push: dict[str, float] = {}

    def _profile(self, channel: str) -> ChannelProfile:
        return self._profiles.get(channel, self._default)

    def push(self, channel: str, text: str) -> str | None:
        if not text:
            return None
        profile = self._profile(channel)
        now = time.monotonic()
        buf = self._buffers.get(channel, "") + text
        started = self._last_push.get(channel, now)
        aged = (now - started) >= profile.max_latency_s
        boundary = should_flush_on_boundary(text, profile)
        if (
            len(buf) >= profile.flush_chars
            or (boundary and len(buf) >= profile.min_chars)
            or ("\n" in text and len(buf) >= profile.min_chars)
            or (aged and len(buf) >= profile.min_chars)
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


@dataclass
class StreamMetrics:
    """Live stream stats — TTFT + tokens/sec for status bar."""

    ttft_ms: int | None = None
    stream_chars: int = 0
    stream_tokens: int = 0
    started_at: float | None = None

    def note_first_token(self, *, ttft_ms: int, at: float | None = None) -> None:
        if self.ttft_ms is None:
            self.ttft_ms = max(0, ttft_ms)
        if self.started_at is None:
            self.started_at = at

    def note_text(self, text: str, *, tokens: int | None = None) -> float:
        import time as _time

        if not text:
            return self.tps
        now = _time.monotonic()
        if self.started_at is None:
            self.started_at = now
        self.stream_chars += len(text)
        if tokens is not None and tokens > 0:
            self.stream_tokens += tokens
        return self.tps

    @property
    def tps(self) -> float:
        import time as _time

        if self.started_at is None or self.stream_chars <= 0:
            return 0.0
        elapsed = _time.monotonic() - self.started_at
        if elapsed <= 0:
            return 0.0
        est = self.stream_tokens if self.stream_tokens > 0 else max(1, self.stream_chars // 4)
        return est / elapsed

    def reset(self) -> None:
        self.ttft_ms = None
        self.stream_chars = 0
        self.stream_tokens = 0
        self.started_at = None


__all__ = [
    "ANSWER_PROFILE",
    "ChannelProfile",
    "StreamCoalescer",
    "StreamMetrics",
    "THINKING_PROFILE",
    "should_flush_on_boundary",
]
