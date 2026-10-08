"""Lightweight repository map — Aider-inspired symbol sketch for orientation."""

from __future__ import annotations

import os
import re
from pathlib import Path

from kite.context.discovery import MAX_SCAN_ENTRIES, SKIP_DIRS

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


def git_changed_paths(root: Path, *, status: str | None = None) -> set[str]:
    """Paths changed vs HEAD, staged, or untracked; reuse an existing status when available."""
    if status is None:
        from kite.context.discovery import git_status_snippet

        status = git_status_snippet(root, max_chars=0)
    changed: set[str] = set()
    for line in status.splitlines():
        if line.startswith("##"):
            continue
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if " -> " in rel:  # renames: keep the new path
            rel = rel.rsplit(" -> ", 1)[-1].strip()
        if len(rel) >= 2 and rel.startswith('"') and rel.endswith('"'):
            rel = rel[1:-1]
        rel = rel.replace("\\", "/")
        if rel:
            changed.add(rel)
    return changed


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


def _rel_posix(path: Path, root: Path, root_str: str) -> str:
    """Use the resolved ancestor prefix, falling back to pathlib for other paths."""
    text = str(path)
    if text.startswith(root_str) and len(text) > len(root_str):
        # Require a separator at the boundary, else a sibling like "...\bc"
        # would slice as if it lived under "...\b".
        tail = text[len(root_str) :]
        if tail[0] in ("\\", "/"):
            return tail[1:].replace("\\", "/")
    return path.relative_to(root).as_posix()


def _score_path(path: Path, root: Path, changed: set[str]) -> tuple[int, str]:
    root_str = str(root)
    rel = _rel_posix(path, root, root_str)
    name = path.name
    depth = len(path.parts)
    score = 0
    if rel in changed:
        score -= 120
    if name in _ENTRY_NAMES:
        score -= 40
    if name.startswith("test_") or name.endswith("_test.py") or "/tests/" in rel:
        score += 30
    if path.suffix == ".py" and "src" in path.parts:
        score -= 10
    return (score + depth, rel.lower())


_MAX_REPO_SCAN_FILES = 600


def _iter_source_files(root: Path) -> list[Path]:
    """Bound source candidates and total entries, pruning ignored/symlink directories."""
    candidates: list[Path] = []
    pending = [root]
    scanned = 0
    while pending and scanned < MAX_SCAN_ENTRIES:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > MAX_SCAN_ENTRIES:
                        return candidates
                    if entry.name in SKIP_DIRS or entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                        continue
                    if os.path.splitext(entry.name)[1].lower() not in _SOURCE_EXTS:
                        continue
                    try:
                        if entry.stat().st_size > 120_000:
                            continue
                    except OSError:
                        continue
                    candidates.append(Path(entry.path))
                    if len(candidates) >= _MAX_REPO_SCAN_FILES:
                        return candidates
        except OSError:
            continue
    return candidates


def build_repo_map(
    root: Path,
    *,
    max_files: int = 36,
    max_defs_per_file: int = 6,
    max_chars: int = 6_000,
    prefer_git_changed: bool = True,
    changed_paths: set[str] | None = None,
) -> str:
    """Return a compact symbol map for prompt injection."""
    root = root.expanduser().resolve()
    changed = changed_paths
    if changed is None:
        changed = git_changed_paths(root) if prefer_git_changed else set()
    candidates = _iter_source_files(root)
    candidates.sort(key=lambda p: _score_path(p, root, changed))
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
        prefix = "*" if rel in changed else ""
        lines.append(f"{prefix}{rel}: {', '.join(defs)}")
        if sum(len(line) + 1 for line in lines) > max_chars:
            break

    if not lines:
        return ""
    body = "\n".join(lines)
    if changed:
        body = f"(* = git-changed)\n{body}"
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n...[truncated]"
    return body
