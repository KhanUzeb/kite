"""Project context discovery — AGENTS.md, git status, tree snippet (tau-inspired)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kite.util.cache import TtlCache

PROJECT_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".kite",
}


@dataclass(frozen=True)
class ContextFile:
    path: str
    content: str


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    cwd: Path
    files: tuple[ContextFile, ...]
    git_status: str
    tree_snippet: str

    def render_for_prompt(self, *, max_chars: int = 24_000) -> str:
        parts: list[str] = [
            f"## Workspace\n- cwd: {self.cwd}\n- project_root: {self.root}",
        ]
        if self.tree_snippet:
            parts.append(f"## Directory sketch\n```\n{self.tree_snippet}\n```")
        if self.git_status:
            parts.append(f"## Git status\n```\n{self.git_status}\n```")
        for cf in self.files:
            parts.append(f"## Project instructions ({cf.path})\n{cf.content.strip()}")
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text


def find_project_root(cwd: Path) -> Path:
    cwd = cwd.expanduser().resolve()
    for path in (cwd, *cwd.parents):
        if any((path / marker).exists() for marker in PROJECT_MARKERS):
            return path
    return cwd


def discover_agents_files(cwd: Path) -> tuple[ContextFile, ...]:
    root = find_project_root(cwd)
    candidates = [
        root / "KITE.md",
        root / "AGENTS.md",
        root / ".kite" / "AGENTS.md",
        root / ".kite" / "KITE.md",
        root / ".agents" / "AGENTS.md",
        cwd / "AGENTS.md",
        cwd / "KITE.md",
    ]
    # ancestor chain from root → cwd
    try:
        rel = cwd.resolve().relative_to(root)
        cur = root
        for part in rel.parts:
            cur = cur / part
            candidates.append(cur / "AGENTS.md")
    except ValueError:
        pass

    seen: set[Path] = set()
    files: list[ContextFile] = []
    for path in candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            continue
        files.append(ContextFile(path=str(resolved), content=content))
    return tuple(files)


def git_status_snippet(cwd: Path, *, max_chars: int = 4_000) -> str:
    try:
        proc = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    out = (proc.stdout or "").strip()
    if len(out) > max_chars:
        return out[: max_chars - 15] + "\n...[truncated]"
    return out


def tree_snippet(root: Path, *, max_entries: int = 80) -> str:
    root = root.expanduser().resolve()
    lines: list[str] = [str(root.name) + "/"]
    count = 0

    def walk(dir_path: Path, prefix: str = "") -> None:
        nonlocal count
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        visible = [e for e in entries if e.name not in SKIP_DIRS and not e.name.startswith(".")]
        for i, entry in enumerate(visible):
            if count >= max_entries:
                lines.append(prefix + "…")
                return
            last = i == len(visible) - 1
            branch = "└── " if last else "├── "
            lines.append(f"{prefix}{branch}{entry.name}{'/' if entry.is_dir() else ''}")
            count += 1
            if entry.is_dir() and count < max_entries:
                extension = "    " if last else "│   "
                walk(entry, prefix + extension)

    walk(root)
    return "\n".join(lines)


_CTX_CACHE: TtlCache[tuple[str, bool, bool, int], ProjectContext] = TtlCache(30.0)


def gather_project_context(
    cwd: str | Path,
    *,
    include_git: bool = True,
    include_tree: bool = True,
    tree_max_entries: int = 80,
) -> ProjectContext:
    cwd_path = Path(cwd).expanduser().resolve()
    key = (str(cwd_path), include_git, include_tree, tree_max_entries)

    def build() -> ProjectContext:
        root = find_project_root(cwd_path)
        return ProjectContext(
            root=root,
            cwd=cwd_path,
            files=discover_agents_files(cwd_path),
            git_status=git_status_snippet(cwd_path) if include_git else "",
            tree_snippet=tree_snippet(root, max_entries=tree_max_entries) if include_tree else "",
        )

    return _CTX_CACHE.get_or_set(key, build)
