"""Behavior/token tests for the conservative prompt-cache breakpoint layout.

Offline structural checks only: they verify message shape and prefix identity,
not provider cache hits or cost savings.
"""

from __future__ import annotations

from kite.context.window import estimate_text_tokens
from kite.models.cache import CacheStats, apply_cache_breakpoints, parse_cache_usage


def _markers(messages: list[dict]) -> list[int]:
    return [
        i
        for i, message in enumerate(messages)
        if isinstance(message.get("content"), list)
        and any(
            isinstance(block, dict) and block.get("cache_control")
            for block in message["content"]
        )
    ]


def _text(messages: list[dict]) -> str:
    """Rendered prompt text only — cache_control metadata is not content."""
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
        parts.append(f"{message.get('role')}:{content}")
    return "\n".join(parts)


def test_only_system_and_setup_or_summary_get_breakpoints() -> None:
    msgs = [
        {"role": "system", "content": "stable instructions"},
        {"role": "user", "content": "# Setup (reference — not the task)\n- cwd: /r"},
        {"role": "user", "content": "do work"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "file contents..."},
        {"role": "assistant", "content": "working on it"},
        {"role": "user", "content": "and now?"},
    ]

    out = apply_cache_breakpoints(msgs, provider="anthropic")

    assert _markers(out) == [0, 1]
    # Tool results and the volatile conversation tail keep their original shape.
    assert isinstance(out[4]["content"], str)
    assert isinstance(out[5]["content"], str)
    assert isinstance(out[6]["content"], str)


def test_summary_is_preferred_over_setup_for_second_breakpoint() -> None:
    msgs = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "Previous conversation summary:\nfoo"},
        {"role": "user", "content": "# Setup (reference — not the task)\n- cwd: /r"},
        {"role": "user", "content": "go"},
    ]

    assert _markers(apply_cache_breakpoints(msgs, provider="anthropic")) == [0, 1]


def test_non_anthropic_and_disabled_leave_messages_untouched() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "result"},
    ]

    assert apply_cache_breakpoints(msgs, provider="openai") == msgs
    assert apply_cache_breakpoints(msgs, provider="anthropic", enabled=False) == msgs


def test_stable_prefix_text_is_identical_across_turns() -> None:
    turn1 = [
        {"role": "system", "content": "stable instructions"},
        {"role": "user", "content": "# Setup (reference — not the task)\n- cwd: /r"},
        {"role": "user", "content": "do work"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "result A"},
    ]
    turn2 = [
        *turn1,
        {"role": "user", "content": "follow up"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "content": "result B"},
    ]

    first = apply_cache_breakpoints(turn1, provider="anthropic")
    second = apply_cache_breakpoints(turn2, provider="anthropic")

    assert _markers(first) == [0, 1]
    assert _markers(second) == [0, 1]
    assert _text(first) == _text(second[: len(first)])
    # Local estimates, never provider cache measurements.
    assert estimate_text_tokens(_text(first)) > 0
    assert estimate_text_tokens(_text(second[: len(first)])) == estimate_text_tokens(_text(first))


def test_provider_cache_fields_are_distinct_from_local_estimates() -> None:
    class Usage:
        prompt_tokens = 900
        completion_tokens = 40
        cache_read_input_tokens = 500
        cache_creation_input_tokens = 100
        prompt_tokens_details = None

    measured = parse_cache_usage(Usage())
    assert measured["cache_read_tokens"] == 500
    assert measured["cache_creation_tokens"] == 100
    assert measured["cached_tokens"] == 0

    none = parse_cache_usage(None)
    assert none["cache_read_tokens"] == 0
    assert none["cache_creation_tokens"] == 0
    assert CacheStats(prompt_tokens=900, cache_read_tokens=500, cache_creation_tokens=100).hit_ratio == 500 / 900
