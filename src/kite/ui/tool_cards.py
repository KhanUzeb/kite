"""Tool card rows — in-flight preview, parallel batch header, done summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from kite.ui.diff import render_diff_stat
from kite.ui.style import GUTTER, PANEL_BAR
from kite.ui.theme import glyph


def _looks_like_json(raw: str) -> bool:
    s = raw.strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


@dataclass(slots=True)
class ToolCard:
    tool: str
    detail: str = ""
    reason: str = ""
    parallel_batch: int = 1
    parallel_index: int = 1


TOOL_BAR = PANEL_BAR


def render_bash_command_block(command: str, *, max_lines: int = 8) -> Text:
    """Terminal-style command preview for tool_start / approval."""
    block = Text()
    lines = (command or "").strip().splitlines() or [""]
    shown = lines[:max_lines]
    for cmd_line in shown:
        block.append(f"{GUTTER}{TOOL_BAR}", style="kite.muted")
        block.append("$ ", style="kite.tool bold")
        block.append(cmd_line + "\n", style="kite.terminal")
    if len(lines) > max_lines:
        block.append(f"{GUTTER}{TOOL_BAR}… +{len(lines) - max_lines} lines\n", style="kite.muted")
    return block


def truncate_preview(text: str, limit: int = 72) -> str:
    raw = (text or "").replace("\n", " ").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def format_partial_args(partial: str, limit: int = 72) -> str:
    raw = (partial or "").strip()
    if not raw:
        return ""
    if _looks_like_json(raw):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                parts = [f"{k}={data[k]!r}" for k in list(data.keys())[:3]]
                return truncate_preview(" ".join(parts), limit)
        except json.JSONDecodeError:
            pass
    return truncate_preview(raw, limit)


def render_parallel_batch_header(count: int) -> Text:
    line = Text()
    line.append(f"{GUTTER}{glyph('tool')} ", style="kite.muted")
    line.append(f"parallel {count} read-only tools", style="kite.tool")
    line.append("\n")
    return line


def render_stream_tool_preview(name: str, partial_args: str) -> Text:
    line = Text()
    line.append(f"{GUTTER}{glyph('tool')} ", style="kite.muted")
    line.append("preparing ", style="kite.muted")
    line.append(name, style="kite.tool")
    preview = format_partial_args(partial_args)
    if preview:
        line.append(f"  {preview}", style="kite.muted")
    line.append("\n")
    return line


def render_tool_card_start(card: ToolCard, *, running: bool = True) -> Text:
    line = Text()
    prefix = ""
    if card.parallel_batch > 1:
        prefix = f"[{card.parallel_index}/{card.parallel_batch}] "
    line.append(f"{GUTTER}{glyph('tool')} ", style="kite.muted")
    line.append(prefix, style="kite.muted")
    line.append(card.tool, style="kite.tool bold")
    if card.detail:
        line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append(card.detail, style="kite.muted")
    if running:
        line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append("running", style="kite.pending italic")
    line.append("\n")
    return line


def render_tool_summary(
    *,
    preview: str = "",
    summary: str = "",
    line_count: int | None = None,
) -> Text | None:
    text = (summary or preview or "").strip().replace("\n", " ")
    if line_count is not None and line_count > 0:
        text = f"{line_count} lines" + (f"  ·  {truncate_preview(text, 56)}" if text else "")
    if not text:
        return None
    line = Text()
    line.append(f"{GUTTER}{GUTTER}", style="kite.muted")
    line.append(truncate_preview(text, 88), style="kite.muted")
    line.append("\n")
    return line


def render_tool_card_done(
    tool: str,
    *,
    ok: bool = True,
    warn: bool = False,
    meta: str = "",
    added: int | None = None,
    deleted: int | None = None,
    preview: str = "",
    summary: str = "",
) -> Text:
    if warn:
        mark, style = glyph("warn"), "kite.pending"
    elif ok:
        mark, style = glyph("ok"), "kite.success"
    else:
        mark, style = glyph("fail"), "kite.error"
    line = Text()
    line.append(f"{GUTTER}{mark} ", style=style)
    line.append(tool, style=style)
    if meta:
        line.append(f"  {meta}", style="kite.muted")
    if added is not None or deleted is not None:
        line.append("  ")
        line.append_text(render_diff_stat(added or 0, deleted or 0, bar=False))
    note = truncate_preview(summary or preview, 64)
    if note and not (added or deleted):
        line.append(f"  {note}", style="kite.muted")
    line.append("\n")
    return line


def line_count_from_output(output: str) -> int | None:
    if not output:
        return None
    lines = [ln for ln in output.splitlines() if ln.strip()]
    return len(lines) if lines else None


def detail_from_args(tool: str, args: dict[str, Any], *, limit: int = 60) -> str:
    if not isinstance(args, dict):
        return ""
    for key in ("path", "command", "pattern", "query", "name", "prompt", "url"):
        if key in args and args[key] is not None:
            val = str(args[key]).replace("\n", " ")
            if len(val) > limit:
                val = val[: limit - 1] + "…"
            return val
    return truncate_preview(json.dumps(args, ensure_ascii=False), limit)
