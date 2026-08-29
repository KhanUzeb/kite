"""Unified-diff rendering — never dump full files."""

from __future__ import annotations

import difflib
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text

from kite.ui.style import (
    DIFF_PREVIEW_LINES,
    GUTTER,
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


__all__ = ["make_unified_diff", "render_diff", "guess_lexer", "syntax_block"]
