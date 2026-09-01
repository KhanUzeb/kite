"""Context compaction ratio threshold."""

from __future__ import annotations

from kite.context.window import ContextUsage, should_compact


def test_should_compact_at_eighty_percent() -> None:
    usage = ContextUsage(
        total_tokens=102_400,
        system_tokens=1000,
        message_tokens=101_400,
        tool_tokens=0,
        message_count=10,
        window=128_000,
    )
    assert should_compact(usage, ratio=0.80)
    assert not should_compact(usage, ratio=0.85)
