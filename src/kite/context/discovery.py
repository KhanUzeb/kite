"""Project context discovery — AGENTS.md, git status, tree snippet (tau-inspired)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kite.util.cache import TtlCache

try:
    from kite.context.repomap import build_repo_map
except ImportError:  # pragma: no cover
    build_repo_map = None  # type: ignore[assignment,misc]

PROJECT_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")
INSTRUCTION_BASENAMES = frozenset({"KITE.md", "AGENTS.md", "CONTEXT.md"})
MAX_INSTRUCTION_FILE_CHARS = 8_000
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
    repo_map: str = ""
    verification_command: str = ""
    verification_source: str = ""  # ci | manifest | empty

    def render_for_prompt(self, *, max_chars: int = 12_000) -> str:
        from kite.context.project_init import agent_nudges_markdown

        parts: list[str] = []
        for cf in self.files:
            parts.append(f"## Project instructions ({cf.path})\n{cf.content.strip()}")
        parts.extend(
            [
                f"## Workspace\n- cwd: {self.cwd}\n- project_root: {self.root}",
            ]
        )
        nudges = agent_nudges_markdown(self.root)
        if nudges:
            parts.append(nudges)
        if self.verification_command:
            src = self.verification_source or "detected"
            parts.append(
                f"## Canonical verification ({src})\n"
                f"Prefer this command before claiming done:\n`{self.verification_command}`"
            )
        if self.repo_map:
            parts.append(f"## Repo map (symbols)\n```\n{self.repo_map}\n```")
        if self.tree_snippet:
            parts.append(f"## Directory sketch\n```\n{self.tree_snippet}\n```")
        if self.git_status:
            parts.append(f"## Git status\n```\n{self.git_status}\n```")
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


def _instruction_candidates(cwd: Path, root: Path) -> list[Path]:
    candidates = [
        root / "KITE.md",
        root / "AGENTS.md",
        root / "CONTEXT.md",
        root / ".kite" / "AGENTS.md",
        root / ".kite" / "KITE.md",
        root / ".kite" / "CONTEXT.md",
        root / ".agents" / "AGENTS.md",
        cwd / "AGENTS.md",
        cwd / "CONTEXT.md",
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
    return candidates


def discover_agents_files(cwd: Path) -> tuple[ContextFile, ...]:
    root = find_project_root(cwd)
    candidates = _instruction_candidates(cwd, root)

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
        except UnicodeDecodeError:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > MAX_INSTRUCTION_FILE_CHARS:
            content = content[: MAX_INSTRUCTION_FILE_CHARS - 20] + "\n\n...[truncated]..."
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


def _instructions_fingerprint(cwd_path: Path) -> tuple[tuple[str, int, int], ...]:
    """Cheap stat fingerprint of instruction files + git HEAD/index.

    Used to invalidate the project-context cache when AGENTS.md/KITE.md (or
    the checked-out commit) changes. Untracked/unstaged working-tree edits
    do not move HEAD, so git status is additionally refreshed on cache hits.
    """
    try:
        root = find_project_root(cwd_path)
    except OSError:
        return ()
    seen: set[Path] = set()
    fp: list[tuple[str, int, int]] = []
    for path in _instruction_candidates(cwd_path, root):
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            st = resolved.stat()
        except OSError:
            continue
        fp.append((str(resolved), st.st_mtime_ns, st.st_size))
    for marker in (root / ".git" / "HEAD", root / ".git" / "index"):
        try:
            st = marker.stat()
        except OSError:
            continue
        fp.append((str(marker), st.st_mtime_ns, st.st_size))
    return tuple(sorted(fp))


_CTX_CACHE: TtlCache[tuple[str, bool, bool, bool, int, tuple], ProjectContext] = TtlCache(
    120.0, maxsize=8
)


def invalidate_project_context_cache() -> None:
    _CTX_CACHE.clear()


def gather_project_context(
    cwd: str | Path,
    *,
    include_git: bool = True,
    include_tree: bool = True,
    include_repo_map: bool = True,
    tree_max_entries: int = 80,
) -> ProjectContext:
    cwd_path = Path(cwd).expanduser().resolve()
    fingerprint = _instructions_fingerprint(cwd_path)
    key = (str(cwd_path), include_git, include_tree, include_repo_map, tree_max_entries, fingerprint)

    cached = _CTX_CACHE.get(key)
    if cached is not None:
        if include_git:
            # Unstaged/working-tree edits do not move HEAD, so refresh the
            # cheap status snippet instead of serving a stale one.
            fresh_status = git_status_snippet(cwd_path)
            if fresh_status != cached.git_status:
                from dataclasses import replace

                cached = replace(cached, git_status=fresh_status)
                _CTX_CACHE.set(key, cached)
        return cached

    def build() -> ProjectContext:
        from kite.context.verify_hint import resolve_verification_command

        root = find_project_root(cwd_path)
        repo_map = ""
        if include_repo_map and build_repo_map is not None:
            repo_map = build_repo_map(root, max_chars=4_000)
        verify_cmd, verify_src = resolve_verification_command(root)
        return ProjectContext(
            root=root,
            cwd=cwd_path,
            files=discover_agents_files(cwd_path),
            git_status=git_status_snippet(cwd_path) if include_git else "",
            tree_snippet=tree_snippet(root, max_entries=tree_max_entries) if include_tree else "",
            repo_map=repo_map,
            verification_command=verify_cmd,
            verification_source=verify_src,
        )

    ctx = build()
    _CTX_CACHE.set(key, ctx)
    return ctx
