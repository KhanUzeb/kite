"""Textual busy-mode composer dispatch."""

from __future__ import annotations

from kite.ui.complete import classify_busy_line


def test_classify_busy_queue_text() -> None:
    result = classify_busy_line("follow up question")
    assert result.kind == "text"


def test_classify_busy_steer_slash() -> None:
    result = classify_busy_line("/steer fix the import")
    assert result.kind == "steer"
    assert "import" in result.text


def test_classify_busy_stop() -> None:
    assert classify_busy_line("/stop").kind == "stop"
