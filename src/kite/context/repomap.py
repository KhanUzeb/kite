"""Lightweight repository map — Aider-inspired symbol sketch for orientation."""

from __future__ import annotations

import re
from pathlib import Path

from kite.context.discovery import SKIP_DIRS

_SOURCE_EXTS = frozenset({".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs"})
_ENTRY_NAMES = frozenset(
    {
        "main.py",
        "app.py",
        "cli.py",
        "index.ts",
        "index.js",
        "main.go",
        "main.rs",
        "lib.rs",
    }
)

_PY_DEF = re.compile(r"^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)", re.MULTILINE)
_JS_DEF = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|^(?:export\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_GO_DEF = re.compile(r"^func\s+(\w+)|^type\s+(\w+)\s+struct", re.MULTILINE)
_RUST_DEF = re.compile(r"^(?:pub\s+)?fn\s+(\w+)|^(?:pub\s+)?(?:struct|enum)\s+(\w+)", re.MULTILINE)


def _defs_for(path: Path, text: str, *, limit: int) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".py":
        matches = _PY_DEF.findall(text)
    elif ext in {".js", ".ts", ".tsx", ".jsx"}:
        matches = _JS_DEF.findall(text)
    elif ext == ".go":
        matches = _GO_DEF.findall(text)
    elif ext == ".rs":
        matches = _RUST_DEF.findall(text)
    else:
        return []
    names: list[str] = []
    for groups in matches:
        for name in groups:
            if name and name not in names:
                names.append(name)
            if len(names) >= limit:
                return names
    return names


def _score_path(path: Path) -> tuple[int, str]:
    name = path.name
    depth = len(path.parts)
    score = 0
    if name in _ENTRY_NAMES:
        score -= 40
    if name.startswith("test_") or name.endswith("_test.py") or "/tests/" in str(path):
        score += 30
    if path.suffix == ".py" and "src" in path.parts:
        score -= 10
    return (score + depth, name.lower())


def build_repo_map(
    root: Path,
    *,
    max_files: int = 36,
    max_defs_per_file: int = 6,
    max_chars: int = 6_000,
) -> str:
    """Return a compact symbol map for prompt injection."""
    root = root.expanduser().resolve()
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SOURCE_EXTS:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        try:
            if path.stat().st_size > 120_000:
                continue
        except OSError:
            continue
        candidates.append(path)

    candidates.sort(key=_score_path)
    lines: list[str] = []
    for path in candidates[:max_files]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        defs = _defs_for(path, text, limit=max_defs_per_file)
        if not defs:
            continue
        rel = path.relative_to(root).as_posix()
        lines.append(f"{rel}: {', '.join(defs)}")
        if sum(len(line) + 1 for line in lines) > max_chars:
            break

    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n...[truncated]"
    return body
