"""Stream coalescing and tool card rendering."""

from __future__ import annotations

from kite.ui.stream_buffer import StreamCoalescer
from kite.ui.tool_cards import (
    ToolCard,
    format_partial_args,
    line_count_from_output,
    render_parallel_batch_header,
    render_stream_tool_preview,
    render_tool_card_done,
    render_tool_card_start,
    render_tool_summary,
    truncate_preview,
)


def test_stream_coalescer_batches_small_chunks() -> None:
    buf = StreamCoalescer(min_chars=5, flush_chars=13)
    assert buf.push("answer", "hi") is None
    assert buf.push("answer", " there world") == "hi there world"
    assert buf.push("answer", "x") is None


def test_stream_coalescer_flush_remaining() -> None:
    buf = StreamCoalescer()
    buf.push("thinking", "partial")
    flushed = buf.flush()
    assert flushed["thinking"] == "partial"


def test_format_partial_args_json() -> None:
    text = format_partial_args('{"path": "src/foo.py", "limit": 10}')
    assert "path=" in text


def test_tool_card_start_parallel() -> None:
    card = ToolCard(tool="read", detail="src/a.py", parallel_batch=3, parallel_index=2)
    plain = render_tool_card_start(card).plain
    assert "[2/3]" in plain
    assert "read" in plain


def test_parallel_batch_header() -> None:
    assert "parallel 3" in render_parallel_batch_header(3).plain


def test_stream_tool_preview() -> None:
    plain = render_stream_tool_preview("grep", '{"pattern": "foo"}').plain
    assert "preparing" in plain
    assert "grep" in plain


def test_tool_card_done_with_diff_stat() -> None:
    from tests.conftest import strip_ansi

    plain = strip_ansi(render_tool_card_done("edit", ok=True, meta="12ms", added=2, deleted=1).plain)
    assert "+2,-1" in plain


def test_line_count_from_output() -> None:
    assert line_count_from_output("a\nb\n\n") == 2


def test_render_tool_summary_lines() -> None:
    line = render_tool_summary(line_count=42, preview="file contents")
    assert line is not None
    assert "42 lines" in line.plain
