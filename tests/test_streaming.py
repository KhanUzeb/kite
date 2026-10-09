"""Token streaming — coalescer, channel split, model delta extraction."""

from __future__ import annotations

import pytest

from kite.models.litellm_model import extract_reasoning_and_content
from kite.ui.streaming import (
    ANSWER_PROFILE,
    StreamCoalescer,
    StreamMetrics,
    should_flush_on_boundary,
)


def test_extract_reasoning_splits_channels() -> None:
    delta = {
        "reasoning_content": "think step",
        "content": "answer bit",
    }
    reasoning, answer = extract_reasoning_and_content(delta)
    assert reasoning == "think step"
    assert answer == "answer bit"

    parts_delta = {
        "content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "hi"},
        ]
    }
    reasoning, answer = extract_reasoning_and_content(parts_delta)
    assert "hmm" in reasoning
    assert answer == "hi"


def test_coalescer_answer_thinking_and_latency(monkeypatch) -> None:
    import kite.ui.streaming as streaming_mod

    now = 1000.0
    monkeypatch.setattr(streaming_mod.time, "monotonic", lambda: now)
    assert should_flush_on_boundary("done.\n", ANSWER_PROFILE)
    assert should_flush_on_boundary("wait", ANSWER_PROFILE) is False

    answer = StreamCoalescer(profiles={"answer": ANSWER_PROFILE})
    assert answer.push("answer", "Hel") is None
    flushed = answer.push("answer", "lo.")
    assert flushed == "Hello."

    thinking = StreamCoalescer()
    assert thinking.push("thinking", "short") is None
    big = "x" * 200
    assert thinking.push("thinking", big) == "short" + big

    latency = StreamCoalescer(profiles={"answer": ANSWER_PROFILE})
    assert latency.push("answer", "ab") is None
    now += ANSWER_PROFILE.max_latency_s + 0.001
    assert latency.push("answer", "c") == "abc"


def test_stream_metrics_preserve_first_token_and_reset(monkeypatch) -> None:
    import kite.ui.streaming as streaming_mod

    now = 1000.0
    monkeypatch.setattr(streaming_mod.time, "monotonic", lambda: now)
    metrics = StreamMetrics()
    assert metrics.tps == 0
    metrics.note_first_token(ttft_ms=120)
    now += 2
    metrics.note_first_token(ttft_ms=999)
    metrics.note_text("hello world")
    assert metrics.ttft_ms == 120
    assert metrics.stream_chars == 11
    assert metrics.tps == pytest.approx(1.0)

    metrics.note_text("!", tokens=5)
    assert metrics.stream_chars == 12
    assert metrics.tps == pytest.approx(2.5)
    metrics.reset()
    assert metrics.ttft_ms is None and metrics.started_at is None
    assert metrics.stream_chars == metrics.stream_tokens == 0
    assert metrics.tps == 0

