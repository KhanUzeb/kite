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


def test_answer_coalescer_flushes_on_boundary() -> None:
    coalescer = StreamCoalescer(profiles={"answer": ANSWER_PROFILE})
    assert coalescer.push("answer", "Hel") is None
    flushed = coalescer.push("answer", "lo.")
    assert flushed == "Hello."


def test_thinking_coalescer_batches_longer() -> None:
    coalescer = StreamCoalescer()
    assert coalescer.push("thinking", "short") is None
    big = "x" * 200
    assert coalescer.push("thinking", big) == "short" + big


def test_coalescer_latency_flush() -> None:
    coalescer = StreamCoalescer(profiles={"answer": ANSWER_PROFILE})
    assert coalescer.push("answer", "ab") is None
    time.sleep(0.03)
    flushed = coalescer.push("answer", "c")
    assert flushed == "abc"


def test_boundary_detector() -> None:
    assert should_flush_on_boundary("done.\n", ANSWER_PROFILE)
    assert should_flush_on_boundary("wait", ANSWER_PROFILE) is False


def test_stream_metrics_tps() -> None:
    metrics = StreamMetrics()
    metrics.note_first_token(ttft_ms=120)
    metrics.note_text("hello world")
    assert metrics.ttft_ms == 120
    assert metrics.stream_chars == 11
    assert metrics.tps > 0
