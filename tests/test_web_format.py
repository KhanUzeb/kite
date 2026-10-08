"""Web output formatting helpers."""

from __future__ import annotations

from kite.tools.web_format import slice_body_text


def test_slice_body_text_lines() -> None:
    text = "\n".join(f"line {i}" for i in range(10))
    sliced, truncated = slice_body_text(text, max_lines=3)
    assert truncated is True
    assert sliced == "line 0\nline 1\nline 2"
    assert slice_body_text(sliced, max_lines=3) == (sliced, False)
    assert slice_body_text(text, start=7, max_lines=2) == ("line 1\nline 2", True)
    assert slice_body_text(text, start=len(text), max_lines=3) == ("", False)
