"""Loop-level context compaction (called each turn before query)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kite.context.window import (
    ContextUsage,
    compact_messages,
    estimate_usage,
    should_compact,
)
from kite.events import Event


@dataclass
class CompactionConfig:
    enabled: bool = True
    window: int = 128_000
    reserve_tokens: int = 16_384
    keep_recent_tokens: int = 20_000


@dataclass
class CompactionResult:
    messages: list[dict]
    usage: ContextUsage
    compacted: bool
    before: int
    after: int


class LoopCompactor:
    """Owns the pre-query compaction decision for the agent loop."""

    def __init__(
        self,
        config: CompactionConfig,
        *,
        system: str = "",
        tool_schemas: list[dict] | None = None,
        on_event: Callable[[Event], None] | None = None,
    ):
        self.config = config
        self.system = system
        self.tool_schemas = tool_schemas or []
        self.on_event = on_event
        self.last_usage: ContextUsage | None = None

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def measure(self, messages: list[dict]) -> ContextUsage:
        usage = estimate_usage(
            system=self.system,
            messages=messages,
            tool_schemas=self.tool_schemas,
            window=self.config.window,
        )
        self.last_usage = usage
        self._emit(
            "context",
            total_tokens=usage.total_tokens,
            window=usage.window,
            ratio=round(usage.ratio, 3),
            remaining=usage.remaining,
        )
        return usage

    def maybe_compact(self, messages: list[dict]) -> CompactionResult:
        usage = self.measure(messages)
        before = len(messages)
        if not self.config.enabled or not should_compact(usage, reserve=self.config.reserve_tokens):
            return CompactionResult(messages=messages, usage=usage, compacted=False, before=before, after=before)

        compacted = compact_messages(
            messages,
            keep_recent_tokens=self.config.keep_recent_tokens,
        )
        after = len(compacted)
        did = after != before or compacted is not messages
        # detect real change
        did = compacted != messages
        if did:
            self._emit("compact", before=before, after=after)
            usage = self.measure(compacted)
        return CompactionResult(
            messages=compacted,
            usage=usage,
            compacted=did,
            before=before,
            after=after,
        )
