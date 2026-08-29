"""Unified-diff rendering — never dump full files."""

from __future__ import annotations

import difflib
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text

from kite.ui.style import (
    DIFF_PREVIEW_LINES,
    GUTTER,
    PREVIEW_CHUNK_BYTES,
    PREVIEW_FILE_MAX_BYTES,
    SYMBOL_COLLAPSE,
    SYMBOL_EXPAND,
    syntax_theme,
)


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
    return "\n".join(lines) + "\n"


def preview_write_diff(path: str, content: str, *, existing_bytes: int | None) -> str:
    """Approval preview for write — uses args; notes size when replacing a large file."""
    rel = path.replace("\\", "/")
    if existing_bytes is None:
        return make_unified_diff(path, "", content)
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
    return header + body


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
            return make_unified_diff(rel, "", content)
        size = path.stat().st_size
        if size <= PREVIEW_FILE_MAX_BYTES:
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
            return make_unified_diff(rel, before, content)
        return preview_write_diff(rel, content, existing_bytes=size)

    if tool == "edit":
        old, new = str(args.get("old") or ""), str(args.get("new") or "")
        if path.is_file() and old and not file_contains(path, old):
            return f"--- a/{rel}\n+++ b/{rel}\n@@ warning @@\n-old text not found in file\n"
        if path.is_file() and path.stat().st_size <= PREVIEW_FILE_MAX_BYTES:
            try:
                before = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
            if args.get("replace_all"):
                after = before.replace(old, new)
            else:
                after = before.replace(old, new, 1)
            return make_unified_diff(rel, before, after)
        return preview_patch_diff(rel, old, new)

    return ""


def render_diff(
    diff: str,
    *,
    collapsed: bool = False,
    language: str | None = None,
    theme: str = "ansi_dark",
):
    if not diff.strip():
        t = Text(f"{GUTTER}(empty diff)", style="kite.muted")
        return t

    lines = diff.splitlines()
    shown = lines if not collapsed else lines[:DIFF_PREVIEW_LINES]
    body = Text()
    for line in shown:
        style = "kite.diff.meta"
        if line.startswith("+++") or line.startswith("---"):
            style = "kite.diff.meta"
        elif line.startswith("@@"):
            style = "kite.diff.hunk"
        elif line.startswith("+"):
            style = "kite.diff.add"
        elif line.startswith("-"):
            style = "kite.diff.del"
        body.append(GUTTER + GUTTER)
        body.append(line + "\n", style=style)
    extra = len(lines) - len(shown)
    if extra > 0:
        glyph = SYMBOL_EXPAND if not collapsed else SYMBOL_COLLAPSE
        hint = "/expand" if collapsed else "/collapse"
        body.append(f"{GUTTER}{GUTTER}{glyph} +{extra} lines  {hint}\n", style="kite.muted")
    return body


def guess_lexer(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "tsx",
        "js": "javascript",
        "jsx": "jsx",
        "go": "go",
        "rs": "rust",
        "toml": "toml",
        "md": "markdown",
        "json": "json",
        "yml": "yaml",
        "yaml": "yaml",
        "sh": "bash",
        "ps1": "powershell",
    }.get(ext, "text")


def syntax_block(code: str, path: str, console) -> Syntax:
    return Syntax(
        code,
        guess_lexer(path),
        theme=syntax_theme(console),
        line_numbers=False,
        word_wrap=False,
        background_color="default",
    )


__all__ = [
    "make_unified_diff",
    "preview_mutating_diff",
    "preview_patch_diff",
    "preview_write_diff",
    "file_contains",
    "render_diff",
    "guess_lexer",
    "syntax_block",
]
