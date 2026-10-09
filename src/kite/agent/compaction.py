"""Loop-level context compaction (called each turn before query)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kite.agent.events import Event
from kite.context.window import (
    ContextUsage,
    estimate_message_tokens,
    estimate_text_tokens,
    estimate_tool_schema_tokens,
    scale_compaction_llm_ratio,
    should_compact,
)
from kite.memory.compaction_ops import run_compaction


@dataclass
class CompactionConfig:
    enabled: bool = True
    window: int = 128_000
    # 0 = auto: scale with ``window`` (see context.window). A positive value is
    # an explicit user override and wins over the scaling.
    reserve_tokens: int = 0
    keep_recent_tokens: int = 12_000
    compact_ratio: float = 0.0
    compaction_llm_ratio: float = 0.0


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
        summarizer: Callable[[list[dict]], str] | None = None,
        session_id: str | None = None,
        cwd: str = "",
        todos: list[dict] | None = None,
        session_meta: dict | None = None,
        extra_facts: list[str] | None = None,
    ):
        self.config = config
        self.system = system
        self.tool_schemas = tool_schemas or []
        self.on_event = on_event
        self.summarizer = summarizer
        self.session_id = session_id
        self.cwd = cwd
        self.todos = todos
        self.session_meta = session_meta
        self.extra_facts = list(extra_facts or [])
        self.last_usage: ContextUsage | None = None
        self._checkpoint_keys: set[str] = set()
        self._tool_tokens = estimate_tool_schema_tokens(self.tool_schemas)
        self._measured_messages: list[dict] | None = None
        self._measured_count = 0

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def measure(self, messages: list[dict], *, append_only: bool = False) -> ContextUsage:
        """Measure arbitrary history, or just its tail when the caller owns an append-only prefix."""
        start = 0
        message_tokens = 0
        message_count = 0
        if (
            append_only
            and messages is self._measured_messages
            and len(messages) >= self._measured_count
            and self.last_usage is not None
        ):
            start = self._measured_count
            message_tokens = self.last_usage.message_tokens
            message_count = self.last_usage.message_count
        for index in range(start, len(messages)):
            message = messages[index]
            if message.get("role") != "exit":
                message_tokens += estimate_message_tokens(message)
                message_count += 1
        system_tokens = estimate_text_tokens(self.system)
        total = system_tokens + message_tokens + self._tool_tokens
        if messages and messages[0].get("role") == "system" and self.system:
            total -= estimate_text_tokens(str(messages[0].get("content") or ""))
        usage = ContextUsage(
            total_tokens=max(0, total),
            system_tokens=system_tokens,
            message_tokens=message_tokens,
            tool_tokens=self._tool_tokens,
            message_count=message_count,
            window=self.config.window,
        )
        self._measured_messages = messages
        self._measured_count = len(messages)
        if usage == self.last_usage:
            return self.last_usage
        self.last_usage = usage
        self._emit(
            "context",
            total_tokens=usage.total_tokens,
            window=usage.window,
            ratio=round(usage.ratio, 3),
            remaining=usage.remaining,
        )
        return usage

    def maybe_compact(
        self, messages: list[dict], *, force: bool = False, append_only: bool = False
    ) -> CompactionResult:
        usage = self.measure(messages, append_only=append_only)
        before = len(messages)

        checkpoint = None
        if self.session_id:
            from kite.memory.compaction_ops import maybe_checkpoint_before_compact

            checkpoint = maybe_checkpoint_before_compact(
                session_id=self.session_id,
                messages=messages,
                cwd=self.cwd,
                usage=usage,
                todos=self.todos,
                meta=self.session_meta,
                system=self.system,
                tool_schemas=self.tool_schemas,
                already_checkpoints=self._checkpoint_keys,
            )
            if checkpoint is not None:
                self._emit(
                    "checkpoint",
                    id=checkpoint.id,
                    label=checkpoint.label,
                    reason=checkpoint.reason,
                    tokens=checkpoint.context_usage.get("total_tokens"),
                )

        if not force and (
            not self.config.enabled
            or not should_compact(usage, reserve=self.config.reserve_tokens, ratio=self.config.compact_ratio)
        ):
            return CompactionResult(messages=messages, usage=usage, compacted=False, before=before, after=before)

        llm_ratio = scale_compaction_llm_ratio(
            self.config.window,
            self.config.compaction_llm_ratio,
        )

        self._emit(
            "compaction_start",
            before=before,
            total_tokens=usage.total_tokens,
            window=usage.window,
            ratio=round(usage.ratio, 3),
        )
        self._emit("tool_progress", tool="compact", elapsed_s=0, hint="")

        summarizer = self.summarizer
        if summarizer and usage.ratio < llm_ratio:
            summarizer = None

        result = run_compaction(
            messages,
            system=self.system,
            tool_schemas=self.tool_schemas,
            window=self.config.window,
            reserve_tokens=self.config.reserve_tokens,
            keep_recent_tokens=self.config.keep_recent_tokens,
            compact_ratio=self.config.compact_ratio,
            # Already resolved against the window above; run_compaction would
            # scale it again against its own window value.
            compaction_llm_ratio=llm_ratio,
            summarizer=summarizer,
            force=force,
            enabled=self.config.enabled,
            session_id=self.session_id,
            cwd=self.cwd,
            checkpoint_before=False,
            extra_facts=self.extra_facts,
        )
        after = result.after
        did = result.compacted
        if did:
            usage = self.measure(result.messages)
            self._emit(
                "compact",
                before=before,
                after=after,
                total_tokens=usage.total_tokens,
                window=usage.window,
                ratio=round(usage.ratio, 3),
            )
        self._emit(
            "compaction_end",
            before=before,
            after=after,
            compacted=did,
            total_tokens=usage.total_tokens,
            window=usage.window,
            ratio=round(usage.ratio, 3),
        )
        return CompactionResult(
            messages=result.messages,
            usage=usage,
            compacted=did,
            before=before,
            after=after,
        )
