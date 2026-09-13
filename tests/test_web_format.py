"""Web output formatting helpers."""

from __future__ import annotations

from kite.tools.web_format import format_search_output, slice_body_text


def test_format_search_urls_only() -> None:
    results = [{"title": "T", "url": "https://a.com", "snippet": "long snippet"}]
    out = format_search_output("q", results, engine="ddg", urls_only=True)
    assert "https://a.com" in out
    assert "long snippet" not in out


def test_slice_body_text_lines() -> None:
    text = "\n".join(f"line {i}" for i in range(10))
    sliced, truncated = slice_body_text(text, max_lines=3)
    assert truncated is True
    assert sliced.count("\n") == 2
