"""Shared compaction operations — REPL, loop, and CLI use the same path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kite.context.window import ContextUsage, compact_messages, estimate_usage, should_compact
from kite.memory.context_checkpoint import ContextCheckpoint, save_checkpoint


@dataclass
class CompactionRunResult:
    messages: list[dict]
    compacted: bool
    before: int
    after: int
    usage: ContextUsage
    checkpoint: ContextCheckpoint | None = None


def maybe_checkpoint_before_compact(
    *,
    session_id: str,
    messages: list[dict],
    cwd: str,
    usage: ContextUsage,
    checkpoint_ratio: float = 0.72,
    todos: list[dict] | None = None,
    meta: dict[str, Any] | None = None,
    system: str = "",
    tool_schemas: list[dict] | None = None,
    already_checkpoints: set[str] | None = None,
) -> ContextCheckpoint | None:
    """Auto-save a checkpoint once when context crosses the soft threshold."""
    if usage.ratio < checkpoint_ratio:
        return None
    key = f"{session_id}:{len(messages)}"
    seen = already_checkpoints or set()
    if key in seen:
        return None
    seen.add(key)
    return save_checkpoint(
        session_id=session_id,
        messages=messages,
        cwd=cwd,
        label="auto pre-compact",
        reason="pre_compact",
        todos=todos,
        meta=meta,
        system=system,
        tool_schemas=tool_schemas,
        window=usage.window,
    )


def run_compaction(
    messages: list[dict],
    *,
    system: str = "",
    tool_schemas: list[dict] | None = None,
    window: int = 128_000,
    reserve_tokens: int = 16_384,
    keep_recent_tokens: int = 20_000,
    summarizer: Callable[[list[dict]], str] | None = None,
    force: bool = False,
    enabled: bool = True,
    session_id: str | None = None,
    cwd: str = "",
    todos: list[dict] | None = None,
    meta: dict[str, Any] | None = None,
    checkpoint_before: bool = True,
    checkpoint_ratio: float = 0.72,
    compact_ratio: float = 0.80,
) -> CompactionRunResult:
    usage = estimate_usage(system=system, messages=messages, tool_schemas=tool_schemas, window=window)
    before = len(messages)
    checkpoint: ContextCheckpoint | None = None

    will_compact = force or (enabled and should_compact(usage, reserve=reserve_tokens, ratio=compact_ratio))
    if will_compact and checkpoint_before and session_id:
        checkpoint = maybe_checkpoint_before_compact(
            session_id=session_id,
            messages=messages,
            cwd=cwd,
            usage=usage,
            checkpoint_ratio=checkpoint_ratio if not force else 0.0,
            todos=todos,
            meta=meta,
            system=system,
            tool_schemas=tool_schemas,
        )

    if not will_compact:
        return CompactionRunResult(
            messages=messages,
            compacted=False,
            before=before,
            after=before,
            usage=usage,
            checkpoint=checkpoint,
        )

    compacted = compact_messages(
        messages,
        keep_recent_tokens=keep_recent_tokens,
        summarizer=summarizer,
        force=force,
    )
    after = len(compacted)
    did = compacted != messages
    if did:
        usage = estimate_usage(system=system, messages=compacted, tool_schemas=tool_schemas, window=window)
    return CompactionRunResult(
        messages=compacted,
        compacted=did,
        before=before,
        after=after,
        usage=usage,
        checkpoint=checkpoint,
    )
