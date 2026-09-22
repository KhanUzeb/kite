"""Token streaming — coalescer, channel split, model delta extraction."""

from __future__ import annotations

import time

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


def test_coalescer_answer_thinking_and_latency() -> None:
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
    time.sleep(0.03)
    assert latency.push("answer", "c") == "abc"


def test_boundary_detector_and_stream_metrics() -> None:
    assert should_flush_on_boundary("done.\n", ANSWER_PROFILE)
    assert should_flush_on_boundary("wait", ANSWER_PROFILE) is False

    metrics = StreamMetrics()
    metrics.note_first_token(ttft_ms=120)
    metrics.note_text("hello world")
    assert metrics.ttft_ms == 120
    assert metrics.stream_chars == 11
    assert metrics.tps > 0
