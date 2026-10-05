"""Tool card rows — in-flight preview, parallel batch header, done summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from kite.tools.cues import tool_cue
from kite.ui.diff import render_diff_stat
from kite.ui.style import GUTTER, PANEL_BAR, PREVIEW_LINES
from kite.ui.theme import glyph

# The overflow marker is the same sentence everywhere a body is cut: what is
# missing, and the one command that brings it back. Kept in one place so the
# write/edit/bash previews cannot drift apart again.
_OVERFLOW_GLYPH = "\u2026"
_OVERFLOW_TEMPLATE = f"{_OVERFLOW_GLYPH} +{{extra}} lines  /last"
# Columns the block spends on ``GUTTER + PANEL_BAR`` before any body text.
_BODY_INDENT_COLUMNS = cell_len(GUTTER) + cell_len(PANEL_BAR)
# One between-fields separator for every tool row, read live so /font applies:
# chips.py and status.py join with the same mark.
def _sep_join() -> str:
    """Between-fields separator on a tool row, read live so /font applies."""
    return f" {glyph('sep')} "
# Before a trailing inline item (the batch's tool names) the separator takes the
# wider house form, same as chips.py and empty.py: two spaces before, one after.
def _item_sep() -> str:
    """Wider house separator before a trailing inline item."""
    return f"  {glyph('sep')} "
# Free-standing metadata (timing, exit code) rides after two spaces with no
# separator glyph — it annotates the row, it is not another field.
_META_GAP = "  "
# Below this a clipped detail is a stub saying nothing, so it is dropped whole.
_MIN_DETAIL_COLUMNS = 12
_MIN_PREVIEW_COLUMNS = 12
# Below this a clipped path names no file, so the row drops the diff-stat
# histogram instead of reducing the path to a bare ellipsis.
_MIN_PATH_COLUMNS = 16


def _live_width(width: int | None) -> int:
    """Caller-supplied width wins; otherwise the one width source in this package."""
    if width is not None:
        return width
    from kite.ui.status import terminal_width

    return terminal_width()


def _clip_tail(text: str, limit: int) -> str:
    """Keep the TAIL of ``text`` and mark the cut at its FRONT.

    A value is recognised by its end: ``target_mo…`` names no file, and
    ``…odule.py`` always does. Used for paths; ``_clip`` is the prose form.
    """
    if cell_len(text) <= limit:
        return text
    if limit < 2:
        return "\u2026"
    out = ""
    for ch in reversed(text):
        if cell_len(ch + out) > limit - 1:
            break
        out = ch + out
    return f"\u2026{out}" if out else "\u2026"


def _clip(text: str, limit: int) -> str:
    """Cut to ``limit`` display columns with an ellipsis — never a silent slice."""
    if cell_len(text) <= limit:
        return text
    if limit < 2:
        return "\u2026"
    out = ""
    for ch in text:
        if cell_len(out + ch) > limit - 1:
            break
        out += ch
    return (out.rstrip() + "\u2026") if out else "\u2026"


def _stat_columns(added: int, deleted: int, *, histogram: bool = True) -> int:
    """Columns ``render_diff_stat`` will actually spend for this patch.

    The histogram is proportional to the change size, so reserving its 24-cell
    worst case for every header clipped a long path to a bare ellipsis on a
    narrow terminal. Reserving the real width keeps the filename readable.
    """
    # ``+N`` and ``,-M`` — six digits each is far past any real patch.
    counts = 2 + 7 + 1 + 7
    total = added + deleted
    if not histogram or not total:
        return counts
    return counts + 2 + min(24, max(6, total if total < 24 else 24))


def _clip_path(path: str, limit: int) -> str:
    """Elide a path from the LEFT so the filename — the identifying part — stays.

    Clipping the tail leaves ``src/kite/ui…``, which names no file at all.
    Degrades in two steps as the row narrows: drop whole leading directories,
    then cut into the last segment from the front. Only a limit too small for
    an ellipsis plus one character yields a bare ``…``.
    """
    if cell_len(path) <= limit:
        return path
    if limit < 2:
        return "\u2026"
    keep = ""
    for part in reversed(path.replace("\\", "/").split("/")):
        candidate = f"{part}/{keep}" if keep else part
        # +1 leaves room for the leading ellipsis when this candidate survives.
        if cell_len(candidate) + 1 > limit:
            break
        keep = candidate
    if keep:
        return f"\u2026/{keep}"[:limit]
    # A single segment that never fits on its own — a bare filename, or a last
    # segment longer than the whole row — keeps its tail. A bare ellipsis here
    # would name no file at all, which is the exact failure the left-clip exists
    # to prevent.
    return _clip_tail(path.replace("\\", "/").split("/")[-1], limit)



def overflow_marker(extra: int) -> str:
    """The one phrasing for a cut body: how many rows, and how to see them all.

    ``/last`` re-prints the whole record; ``/expand`` only reshapes future calls
    and cannot bring back rows that already scrolled by, so it is never named
    here. Callers prepend their own gutter so the row aligns with its block.
    """
    return _OVERFLOW_TEMPLATE.format(extra=extra)


def _body_line(text: str, width: int, *, prefix: str = "") -> str:
    """One body row, clipped to the live width minus its own prefix."""
    return prefix + _clip(text, max(1, width - cell_len(prefix)))


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


def render_code_edit_preview(
    tool: str,
    args: dict[str, Any],
    *,
    max_lines: int = PREVIEW_LINES,
    width: int | None = None,
) -> Text | None:
    """Preview write/edit patches at tool start.

    The path + diff-stat header is metadata, so it always prints; only the body
    honours ``max_lines``. A truncated body names ``/last`` so the user knows
    the rest is one command away instead of simply missing. Rows are clipped to
    the live width so a long path or line never wraps the block raggedly.
    """
    path = str(args.get("path") or args.get("file_path") or "")
    if not path:
        return None
    row_width = _live_width(width)
    block = Text()
    block.append(GUTTER)
    block.append(TOOL_BAR, style="kite.muted")
    added = deleted = 0
    histogram = True
    if tool == "write":
        content = str(args.get("content") or "")
        lines = [ln for ln in content.splitlines() if ln.strip()] or [""]
        added = len(lines)
    elif tool == "edit":
        old = str(args.get("old_string") or args.get("old") or "")
        new = str(args.get("new_string") or args.get("new") or "")
        old_lines = [ln for ln in old.splitlines() if ln.strip()] or ([""] if old else [])
        new_lines = [ln for ln in new.splitlines() if ln.strip()] or ([""] if new else [])
        added, deleted = len(new_lines), len(old_lines)
    # The stat rides after the path on the same row, so the path yields to it.
    # The counts are the information; the histogram is a picture of them. When
    # the row cannot carry both the path AND the histogram, the picture goes —
    # otherwise a narrow window clips the path to a bare ellipsis that names no
    # file at all.
    room = row_width - _BODY_INDENT_COLUMNS - cell_len("  ")
    if room - _stat_columns(added, deleted, histogram=True) < _MIN_PATH_COLUMNS:
        histogram = False
    stat_columns = _stat_columns(added, deleted, histogram=histogram)
    path_room = room - stat_columns
    block.append(_clip_path(path, max(_MIN_PATH_COLUMNS, path_room)), style="kite.tool bold")
    if tool in {"write", "edit"}:
        block.append("  ")
        block.append_text(render_diff_stat(added, deleted, bar=histogram))
    block.append("\n", style="")
    if tool == "write":
        content = str(args.get("content") or "")
        lines = content.splitlines() or [""]
        for line in lines[:max_lines]:
            block.append(f"{GUTTER}{TOOL_BAR}+ ", style="kite.diff.add")
            block.append(_clip(line, max(1, row_width - _BODY_INDENT_COLUMNS - 2)) + "\n", style="kite.diff.add")
        if len(lines) > max_lines:
            # One printed row per raw content line, so the overflow is
            # len(lines) - max_lines: the unfiltered count, matching the rows
            # the loop above skipped.
            block.append(
                f"{GUTTER}{TOOL_BAR}{overflow_marker(len(lines) - max_lines)}\n",
                style="kite.muted",
            )
        return block
    if tool == "edit":
        old = str(args.get("old_string") or args.get("old") or "")
        new = str(args.get("new_string") or args.get("new") or "")
        old_lines = old.splitlines() or [""]
        new_lines = new.splitlines() or [""]
        shown = 0
        for line in old_lines:
            if shown >= max_lines:
                break
            block.append(f"{GUTTER}{TOOL_BAR}− ", style="kite.diff.del")
            block.append(_clip(line, max(1, row_width - _BODY_INDENT_COLUMNS - 2)) + "\n", style="kite.diff.del")
            shown += 1
        for line in new_lines:
            if shown >= max_lines:
                break
            block.append(f"{GUTTER}{TOOL_BAR}+ ", style="kite.diff.add")
            block.append(_clip(line, max(1, row_width - _BODY_INDENT_COLUMNS - 2)) + "\n", style="kite.diff.add")
            shown += 1
        # The budget spans both sides: `shown` filled from old then new, so the
        # hidden count is the combined old+new total minus the rows printed.
        total = len(old_lines) + len(new_lines)
        if total > max_lines:
            block.append(
                f"{GUTTER}{TOOL_BAR}{overflow_marker(total - max_lines)}\n",
                style="kite.muted",
            )
        return block
    return None


def render_bash_command_block(
    command: str, *, max_lines: int = PREVIEW_LINES, width: int | None = None
) -> Text:
    """Terminal-style command preview for tool_start / approval.

    Truncating a multi-line command is safe: the full text already lives in the
    tool args the model sees, so these rows only need to orient the human. Each
    row is clipped to the live width rather than left to the terminal's wrap.
    """
    row_width = _live_width(width)
    block = Text()
    lines = (command or "").strip().splitlines() or [""]
    shown = lines[:max_lines]
    for cmd_line in shown:
        block.append(f"{GUTTER}{TOOL_BAR}", style="kite.muted")
        block.append("$ ", style="kite.tool bold")
        block.append(_clip(cmd_line, max(1, row_width - _BODY_INDENT_COLUMNS - 2)) + "\n", style="kite.terminal")
    if len(lines) > max_lines:
        block.append(
            f"{GUTTER}{TOOL_BAR}{overflow_marker(len(lines) - max_lines)}\n",
            style="kite.muted",
        )
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
                preferred = ("path", "command", "content", "input", "query", "url")
                keys = [key for key in preferred if key in data]
                keys.extend(key for key in data if key not in keys)
                parts = []
                for key in keys[:3]:
                    value = data[key]
                    if isinstance(value, str) and key in {"content", "input"}:
                        value = value.replace("\n", " ")
                    parts.append(f"{key}={value!r}")
                return truncate_preview(" ".join(parts), limit)
        except json.JSONDecodeError:
            pass
    return truncate_preview(raw, limit)


def render_parallel_batch_header(
    count: int, tools: list[str] | None = None, *, width: int | None = None
) -> Text:
    line = Text()
    line.append(f"{GUTTER}{glyph('tool')} ", style="kite.muted")
    label = f"parallel {count} tools"
    names = [t for t in dict.fromkeys(tools or []) if t]
    row_width = _live_width(width)
    used = cell_len(f"{GUTTER}{glyph('tool')} {label}")
    if names:
        # Names ride after the count; drop trailing names rather than wrap.
        keep = list(names)
        joined = ", ".join(names)
        while keep:
            joined = ", ".join(keep)
            if used + len(_item_sep()) + len(joined) <= row_width:
                break
            keep.pop()
        if keep:
            clipped = joined + (", …" if len(keep) < len(names) else "")
            label = f"{label}{_item_sep()}{clipped}"
    line.append(label, style="kite.tool")
    line.append("\n")
    return line


def render_section_break(title: str) -> Text:
    line = Text()
    line.append(f"{GUTTER}{PANEL_BAR}", style="kite.muted")
    line.append(title.strip(), style="kite.muted")
    line.append("\n")
    return line


def render_stream_tool_preview(
    name: str, partial_args: str, *, width: int | None = None
) -> Text:
    line = Text()
    mark, tag = tool_cue(name)
    line.append(f"{GUTTER}{mark} ", style="kite.muted")
    line.append("preparing", style="kite.muted")
    line.append(_sep_join(), style="kite.muted")
    line.append(name, style="kite.tool")
    if tag and tag != name:
        line.append(_sep_join(), style="kite.muted")
        line.append(tag, style="kite.muted")
    preview = format_partial_args(partial_args)
    if preview:
        room = _live_width(width) - line.cell_len - len(_META_GAP)
        if room >= _MIN_PREVIEW_COLUMNS:
            line.append(_META_GAP, style="kite.muted")
            line.append(_clip(preview, room), style="kite.muted")
    line.append("\n")
    return line


def render_tool_card_start(
    card: ToolCard, *, running: bool = True, width: int | None = None
) -> Text:
    """One-line start card: cue, tool, family tag, detail, state.

    The family tag is dropped when it just repeats the tool name (``edit edit``)
    and the detail is dropped rather than left to the terminal's wrap, so the
    row stays one line at any width. ``executing`` is what the reader waits for,
    so it survives every width.
    """
    row_width = _live_width(width)
    line = Text()
    prefix = ""
    if card.parallel_batch > 1:
        prefix = f"[{card.parallel_index}/{card.parallel_batch}] "
    mark, tag = tool_cue(card.tool)
    line.append(f"{GUTTER}{mark} ", style="kite.muted")
    line.append(prefix, style="kite.muted")
    line.append(card.tool, style="kite.tool bold")
    if tag and tag != card.tool:
        line.append(_sep_join(), style="kite.muted")
        line.append(tag, style="kite.muted")
    if card.detail:
        # Reserve its own separator AND the one that precedes the trailing state,
        # or the row overflows by a separator and `executing` wraps to row two.
        reserve = len(_sep_join()) + (len(_sep_join()) + len("executing") if running else 0)
        room = row_width - line.cell_len - reserve
        if room >= _MIN_DETAIL_COLUMNS:
            line.append(_sep_join(), style="kite.muted")
            line.append(_clip(card.detail, room), style="kite.muted")
    if running:
        line.append(_sep_join(), style="kite.muted")
        line.append("executing", style="kite.pending italic")
    line.append("\n")
    return line


def render_tool_summary(
    *,
    preview: str = "",
    summary: str = "",
    line_count: int | None = None,
    width: int | None = None,
) -> Text | None:
    from kite.ui.output_view import format_viewable_output

    text = format_viewable_output(summary or preview).strip().replace("\n", " ")
    if line_count is not None and line_count > 0:
        text = f"{line_count} lines" + (f"{_META_GAP}{truncate_preview(text, 56)}" if text else "")
    if not text:
        return None
    row_width = _live_width(width)
    # The count is the content; the tail is a quote of it and yields first.
    lead = f"{line_count} lines" if line_count is not None and line_count > 0 else ""
    room = row_width - cell_len(f"{GUTTER}{GUTTER}") - len(_META_GAP)
    if lead and cell_len(text) > room:
        room -= len(_META_GAP) + len(_META_GAP)
    line = Text()
    line.append(f"{GUTTER}{GUTTER}", style="kite.muted")
    line.append(_clip(text, max(1, room)), style="kite.muted")
    line.append("\n")
    return line


def render_run_meter(
    *,
    tools: int = 0,
    duration_ms: int | None = None,
    cost: float | None = None,
    tokens: int = 0,
    n_calls: int = 0,
    width: int | None = None,
) -> Text | None:
    """One-line run footer (Pi/Codex: tools · time · cost)."""
    bits: list[str] = []
    if tools:
        bits.append(f"{tools} tool{'s' if tools != 1 else ''}")
    if n_calls:
        bits.append(f"{n_calls} model")
    if duration_ms is not None:
        if duration_ms < 1000:
            bits.append(f"{duration_ms}ms")
        else:
            bits.append(f"{duration_ms / 1000:.1f}s")
    if tokens:
        bits.append(f"{tokens:,} tok")
    if cost is not None and cost > 0:
        bits.append(f"${cost:.3f}")
    if not bits:
        return None
    row_width = _live_width(width)
    line = Text()
    line.append(f"{GUTTER}", style="kite.muted")
    # Drop the least load-bearing bits from the right until the row fits; the
    # tool count and the cost are what the footer is read for.
    for drop in (len(bits) - 1, 0):
        kept = bits[: drop + 1]
        if len(kept) == 1 or cell_len(GUTTER) + cell_len(_sep_join().join(kept)) <= row_width:
            break
    line.append(_sep_join().join(kept), style="kite.muted")
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
    width: int | None = None,
) -> Text:
    """One-line done card: outcome glyph, cue, tool, family tag, meta, note.

    Same rules as the start card: the family tag is dropped when it repeats the
    tool name, and the free-standing note yields its columns to the outcome,
    the timing and the diff stat rather than being left to wrap.
    """
    if warn:
        mark, style = glyph("warn"), "kite.pending"
    elif ok:
        mark, style = glyph("ok"), "kite.success"
    else:
        mark, style = glyph("fail"), "kite.error"
    row_width = _live_width(width)
    line = Text()
    cue, tag = tool_cue(tool)
    line.append(f"{GUTTER}{mark} ", style=style)
    line.append(f"{cue} ", style="kite.muted")
    line.append(tool, style=style)
    if tag and tag != tool:
        line.append(_sep_join(), style="kite.muted")
        line.append(tag, style="kite.muted")
    if meta:
        line.append(f"{_META_GAP}{meta}", style="kite.muted")
    if added is not None or deleted is not None:
        line.append(_META_GAP)
        line.append_text(render_diff_stat(added or 0, deleted or 0, bar=False))
    note = truncate_preview(summary or preview, 64)
    if note and not (added or deleted):
        room = row_width - line.cell_len - len(_META_GAP)
        if room >= _MIN_PREVIEW_COLUMNS:
            line.append(f"{_META_GAP}{_clip(note, room)}", style="kite.muted")
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
