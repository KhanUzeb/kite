"""Unified-diff rendering — never dump full files."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from rich.text import Text

from kite.ui.style import (
    DIFF_PREVIEW_LINES,
    GUTTER,
    PANEL_BAR,
    PREVIEW_CHUNK_BYTES,
    PREVIEW_FILE_MAX_BYTES,
    SYMBOL_COLLAPSE,
    SYMBOL_EXPAND,
)

_DIFF_BAR = PANEL_BAR

#: Banner for edit/write preview text shown before the change is applied —
#: keeps the model from believing the files on disk already changed.
PREVIEW_NOT_APPLIED = "Staged as a proposal — files NOT modified yet."


def _staged(text: str) -> str:
    """Prefix preview text with the not-applied banner (never doubled)."""
    if text.startswith(PREVIEW_NOT_APPLIED):
        return text
    return f"{PREVIEW_NOT_APPLIED}\n{text}" if text else PREVIEW_NOT_APPLIED


def make_unified_diff(path: str, before: str, after: str) -> str:
    rel = path.replace("\\", "/")
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )
    return ("\n".join(lines) + "\n") if lines else ""


def file_contains(path: Path, needle: str) -> bool:
    """Stream-search a file for a substring — O(file) bytes read, bounded memory."""
    if not needle:
        return True
    if not path.is_file():
        return False
    overlap = max(0, len(needle.encode("utf-8")) - 1)
    tail = b""
    with path.open("rb") as f:
        while True:
            chunk = f.read(PREVIEW_CHUNK_BYTES)
            if not chunk:
                return False
            blob = tail + chunk
            if needle.encode("utf-8") in blob:
                return True
            tail = blob[-overlap:] if overlap else b""


def preview_patch_diff(path: str, old: str, new: str) -> str:
    """Approval preview from edit args only — no full file read."""
    rel = path.replace("\\", "/")
    lines = [f"--- a/{rel}", f"+++ b/{rel}", "@@ patch preview @@"]
    for line in old.splitlines():
        lines.append(f"-{line}")
    for line in new.splitlines():
        lines.append(f"+{line}")
    return _staged("\n".join(lines) + "\n")


def preview_write_diff(path: str, content: str, *, existing_bytes: int | None) -> str:
    """Approval preview for write — uses args; notes size when replacing a large file."""
    rel = path.replace("\\", "/")
    if existing_bytes is None:
        return _staged(make_unified_diff(path, "", content))
    header = (
        f"--- a/{rel}\n"
        f"+++ b/{rel}\n"
        f"@@ replaces entire file ({existing_bytes} bytes) @@\n"
    )
    shown = content.splitlines()[:DIFF_PREVIEW_LINES]
    body = "".join(f"+{line}\n" for line in shown)
    extra = len(content.splitlines()) - len(shown)
    if extra > 0:
        body += f"... +{extra} more lines in new content\n"
    return _staged(header + body)


def preview_mutating_diff(
    tool: str,
    path: Path,
    args: dict,
    *,
    cwd: str | Path = ".",
) -> str:
    """Bounded diff for approval — avoids read_text on large files."""
    if not path.is_absolute():
        path = Path(cwd) / path
    rel = str(args.get("path") or path)

    if tool == "write":
        content = str(args.get("content") or "")
        if not path.is_file():
            return _staged(make_unified_diff(rel, "", content))
        size = path.stat().st_size
        if size <= PREVIEW_FILE_MAX_BYTES:
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
            return _staged(make_unified_diff(rel, before, content))
        return preview_write_diff(rel, content, existing_bytes=size)

    if tool == "edit":
        old, new = str(args.get("old") or ""), str(args.get("new") or "")
        if path.is_file() and old and not file_contains(path, old):
            return _staged(f"--- a/{rel}\n+++ b/{rel}\n@@ warning @@\n-old text not found in file\n")
        if path.is_file() and path.stat().st_size <= PREVIEW_FILE_MAX_BYTES:
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
            if args.get("replace_all"):
                after = before.replace(old, new)
            else:
                after = before.replace(old, new, 1)
            return _staged(make_unified_diff(rel, before, after))
        return preview_patch_diff(rel, old, new)

    return ""


def count_diff_lines(diff: str) -> tuple[int, int]:
    """Count added/deleted lines the way `git diff --numstat` does."""
    added = deleted = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def diff_path(diff: str) -> str:
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            return line[6:].strip()
        if line.startswith("+++ "):
            return line[4:].lstrip("b/").strip()
    return ""


def render_diff_stat(
    added: int,
    deleted: int,
    *,
    path: str = "",
    bar: bool = True,
) -> Text:
    """GitHub-style `+125,-21` with optional `++++----` histogram."""
    t = Text()
    if path:
        t.append(path.replace("\\", "/"), style="kite.muted")
        t.append("  ", style="")
    t.append(f"+{added}", style="kite.diff.add")
    t.append(",", style="kite.muted")
    t.append(f"-{deleted}", style="kite.diff.del")
    total = added + deleted
    if bar and total:
        width = min(24, max(6, total if total < 24 else 24))
        pluses = round(width * added / total) if added else 0
        minuses = width - pluses
        if added and pluses == 0:
            pluses, minuses = 1, max(0, minuses - 1)
        if deleted and minuses == 0:
            minuses, pluses = 1, max(0, pluses - 1)
        t.append("  ")
        if pluses:
            t.append("+" * pluses, style="kite.diff.add")
        if minuses:
            t.append("-" * minuses, style="kite.diff.del")
    return t


_WORD_SPLIT = re.compile(r"(\s+)")


def _is_del_line(line: str) -> bool:
    return line.startswith("-") and not line.startswith("---")


def _is_add_line(line: str) -> bool:
    return line.startswith("+") and not line.startswith("+++")


def _split_indent(text: str) -> tuple[str, str]:
    """Split leading spaces/tabs from the rest of a diff content line."""
    idx = 0
    while idx < len(text) and text[idx] in (" ", "\t"):
        idx += 1
    return text[:idx], text[idx:]


def _word_diff_segments(
    old_words: list[str], new_words: list[str]
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Align two word lists; each segment is (text, changed)."""
    old_segs: list[tuple[str, bool]] = []
    new_segs: list[tuple[str, bool]] = []
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            old_segs.append(("".join(old_words[i1:i2]), False))
            new_segs.append(("".join(new_words[j1:j2]), False))
        else:
            if i1 != i2:
                old_segs.append(("".join(old_words[i1:i2]), True))
            if j1 != j2:
                new_segs.append(("".join(new_words[j1:j2]), True))
    return old_segs, new_segs


def _append_pair_side(
    body: Text,
    *,
    sign: str,
    indent: str,
    segments: list[tuple[str, bool]],
    line_no: int | None,
    widths: tuple[int, int],
) -> None:
    """One side of a paired -/+ line: visible indent, changed words in reverse."""
    bar, base = (f"{_DIFF_BAR}− ", "kite.diff.del") if sign == "-" else (f"{_DIFF_BAR}+ ", "kite.diff.add")
    _gutter(body, line_no if sign == "-" else None, line_no if sign == "+" else None, widths)
    body.append(bar, style=base)
    for char in indent:
        body.append("→" if char == "\t" else "·", style="kite.muted dim")
    for text, changed in segments:
        if text:
            body.append(text, style=f"{base} reverse" if changed else base)
    body.append("\n")


def _append_word_pair(
    body: Text,
    old: str,
    new: str,
    *,
    old_no: int | None = None,
    new_no: int | None = None,
    widths: tuple[int, int] = (0, 0),
) -> None:
    """Paired -/+ lines: highlight changed words only, show leading whitespace."""
    old_indent, old_rest = _split_indent(old)
    new_indent, new_rest = _split_indent(new)
    old_segs, new_segs = _word_diff_segments(
        _WORD_SPLIT.split(old_rest), _WORD_SPLIT.split(new_rest)
    )
    _append_pair_side(body, sign="-", indent=old_indent, segments=old_segs, line_no=old_no, widths=widths)
    _append_pair_side(body, sign="+", indent=new_indent, segments=new_segs, line_no=new_no, widths=widths)


def _append_plain_line(
    body: Text,
    line: str,
    *,
    old_no: int | None = None,
    new_no: int | None = None,
    widths: tuple[int, int] = (0, 0),
) -> None:
    """Single diff line exactly as before (headers, hunks, context, unpaired)."""
    bar, content, style = _diff_line_style(line)
    _gutter(body, old_no, new_no, widths)
    body.append(bar, style="kite.muted" if style == "kite.diff.ctx" else style)
    if content:
        body.append(content + "\n", style=style)
    else:
        body.append("\n", style=style)


def _diff_line_style(line: str) -> tuple[str, str, str]:
    """Return (bar_prefix, body, rich_style) for one unified-diff line."""
    if line.startswith("+++") or line.startswith("---"):
        return _DIFF_BAR, line, "kite.diff.meta"
    if line.startswith("@@"):
        return _DIFF_BAR, line, "kite.diff.hunk"
    if line.startswith("+") and not line.startswith("+++"):
        return f"{_DIFF_BAR}+ ", line[1:], "kite.diff.add"
    if line.startswith("-") and not line.startswith("---"):
        return f"{_DIFF_BAR}− ", line[1:], "kite.diff.del"
    if line.startswith(" "):
        return f"{_DIFF_BAR}  ", line[1:], "kite.diff.ctx"
    if not line:
        return _DIFF_BAR, "", "kite.diff.ctx"
    return _DIFF_BAR, line, "kite.diff.meta"


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _line_numbers(lines: list[str]) -> list[tuple[int | None, int | None]]:
    """Per-line (old, new) numbers from the unified hunk headers.

    Context lines advance both counters, ``-`` advances old, ``+`` advances new.
    Meta/hunk rows get ``None``. Lets the renderer print a real gutter instead
    of asking the reader to count lines.
    """
    out: list[tuple[int | None, int | None]] = []
    old = new = 0
    for line in lines:
        m = _HUNK_RE.match(line)
        if m:
            old = int(m.group(1))
            new = int(m.group(3))
            out.append((None, None))
            continue
        if line.startswith("---") or line.startswith("+++"):
            out.append((None, None))
            continue
        if line.startswith("-"):
            out.append((old, None))
            old += 1
            continue
        if line.startswith("+"):
            out.append((None, new))
            new += 1
            continue
        out.append((old, new))
        old += 1
        new += 1
    return out


def _num_widths(numbers: list[tuple[int | None, int | None]]) -> tuple[int, int]:
    old = [str(o) for o, _ in numbers if o is not None]
    new = [str(n) for _, n in numbers if n is not None]
    return (max((len(v) for v in old), default=0), max((len(v) for v in new), default=0))


def _gutter(body: Text, old: int | None, new: int | None, widths: tuple[int, int]) -> None:
    """Dim `old  new` line-number gutter, right-aligned.

    Meta and hunk rows carry no numbers and keep the left edge instead of a
    column of blanks.
    """
    body.append(GUTTER)
    if old is None and new is None:
        return
    ow, nw = widths
    body.append(f"{(str(old) if old is not None else '').rjust(ow)}", style="kite.diff.lineno")
    body.append(" ")
    body.append(f"{(str(new) if new is not None else '').rjust(nw)}", style="kite.diff.lineno")
    body.append(" ")


def render_diff(
    diff: str,
    *,
    collapsed: bool = False,
    max_lines: int | None = None,
    language: str | None = None,
    theme: str = "ansi_dark",
):
    if not diff.strip():
        t = Text(f"{GUTTER}(empty diff)", style="kite.muted")
        return t

    lines = diff.splitlines()
    cap = max_lines if max_lines is not None else DIFF_PREVIEW_LINES
    shown = lines if not collapsed else lines[:cap]
    body = Text()
    added, deleted = count_diff_lines(diff)
    path = diff_path(diff)
    numbers = _line_numbers(shown)
    widths = _num_widths(numbers)
    if path or added or deleted:
        body.append(GUTTER)
        body.append(_DIFF_BAR, style="kite.muted")
        if path:
            body.append(path, style="kite.tool bold")
            if added or deleted:
                body.append("  ", style="")
        if added or deleted:
            body.append_text(render_diff_stat(added, deleted, bar=True))
        body.append("\n")
    idx = 0
    total = len(shown)
    while idx < total:
        line = shown[idx]
        if _is_del_line(line):
            end_del = idx
            while end_del < total and _is_del_line(shown[end_del]):
                end_del += 1
            end_add = end_del
            while end_add < total and _is_add_line(shown[end_add]):
                end_add += 1
            dels, adds = shown[idx:end_del], shown[end_del:end_add]
            pairs = min(len(dels), len(adds))
            for offset, (old_line, new_line) in enumerate(
                zip(dels[:pairs], adds[:pairs], strict=False)
            ):
                _append_word_pair(
                    body,
                    old_line[1:],
                    new_line[1:],
                    old_no=numbers[idx + offset][0],
                    new_no=numbers[end_del + offset][1],
                    widths=widths,
                )
            for offset, rest in enumerate((*dels[pairs:], *adds[pairs:])):
                base = idx + (end_del - idx - pairs) + offset
                _append_plain_line(
                    body,
                    rest,
                    old_no=numbers[base][0],
                    new_no=numbers[base][1],
                    widths=widths,
                )
            idx = end_add
        else:
            _append_plain_line(
                body,
                line,
                old_no=numbers[idx][0],
                new_no=numbers[idx][1],
                widths=widths,
            )
            idx += 1
    extra = len(lines) - len(shown)
    if extra > 0:
        glyph = SYMBOL_EXPAND if not collapsed else SYMBOL_COLLAPSE
        hint = "/expand" if collapsed else "/collapse"
        body.append(f"{GUTTER}{_DIFF_BAR}{glyph} +{extra} lines  {hint}\n", style="kite.muted")
    return body


__all__ = [
    "PREVIEW_NOT_APPLIED",
    "make_unified_diff",
    "count_diff_lines",
    "diff_path",
    "preview_mutating_diff",
    "preview_patch_diff",
    "preview_write_diff",
    "file_contains",
    "render_diff",
    "render_diff_stat",
]
