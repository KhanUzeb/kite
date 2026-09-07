"""Lightweight repository map — Aider-inspired symbol sketch for orientation."""

from __future__ import annotations

import os
import re
import subprocess
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


def git_changed_paths(root: Path) -> set[str]:
    """Paths changed vs HEAD, staged, or untracked — empty when not a git repo."""
    root = root.expanduser().resolve()
    changed: set[str] = set()
    commands = (
        ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
        ["git", "-C", str(root), "diff", "--cached", "--name-only"],
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
    )
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        for line in (proc.stdout or "").splitlines():
            rel = line.strip().replace("\\", "/")
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


def _score_path(path: Path, root: Path, changed: set[str]) -> tuple[int, str]:
    rel = path.relative_to(root).as_posix()
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
    """Walk the tree with skip dirs — capped to avoid stat storms on huge repos."""
    root = root.expanduser().resolve()
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        ]
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if path.suffix.lower() not in _SOURCE_EXTS:
                continue
            try:
                if path.stat().st_size > 120_000:
                    continue
            except OSError:
                continue
            candidates.append(path)
            if len(candidates) >= _MAX_REPO_SCAN_FILES:
                return candidates
    return candidates


def build_repo_map(
    root: Path,
    *,
    max_files: int = 36,
    max_defs_per_file: int = 6,
    max_chars: int = 6_000,
    prefer_git_changed: bool = True,
) -> str:
    """Return a compact symbol map for prompt injection."""
    root = root.expanduser().resolve()
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
