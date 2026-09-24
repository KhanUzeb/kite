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
        """Priority-ordered sections under one budget (instructions > verification > repo map > git > tree).

        Each section is capped to its share before joining, so a huge tree can
        never squeeze out project instructions — the highest-signal section.
        """
        from kite.context.project_init import agent_nudges_markdown

        head = f"## Workspace\n- cwd: {self.cwd}\n- project_root: {self.root}"
        nudges = agent_nudges_markdown(self.root)
        instruction_blocks = [
            f"## Project instructions ({cf.path})\n{cf.content.strip()}" for cf in self.files
        ]
        budgets = _section_budgets(max_chars, has_instructions=bool(instruction_blocks))
        sections: list[str] = [head]
        if nudges:
            sections.append(_cap(nudges, budgets["nudges"]))
        sections.extend(_cap(b, budgets["instructions"]) for b in instruction_blocks)
        if self.verification_command:
            src = self.verification_source or "detected"
            sections.append(
                _cap(
                    f"## Canonical verification ({src})\n"
                    f"Prefer this command before claiming done:\n`{self.verification_command}`",
                    budgets["verification"],
                )
            )
        if self.repo_map:
            sections.append(_cap(f"## Repo map (symbols)\n```\n{self.repo_map}\n```", budgets["repo_map"]))
        if self.git_status:
            sections.append(_cap(f"## Git status\n```\n{self.git_status}\n```", budgets["git"]))
        if self.tree_snippet:
            sections.append(_cap(f"## Directory sketch\n```\n{self.tree_snippet}\n```", budgets["tree"]))
        text = "\n\n".join(sections)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text


def _cap(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    return text[: max(0, budget - 24)] + "\n...[section truncated]..."


def _section_budgets(max_chars: int, *, has_instructions: bool) -> dict[str, int]:
    """Share one budget across sections; instructions always win."""
    if max_chars <= 0:
        return {"nudges": 0, "instructions": 0, "verification": 0, "repo_map": 0, "git": 0, "tree": 0}
    if has_instructions:
        return {
            "nudges": max_chars // 20,
            "instructions": max_chars // 2,
            "verification": max_chars // 10,
            "repo_map": max_chars // 5,
            "git": max_chars // 10,
            "tree": max_chars // 10,
        }
    return {
        "nudges": max_chars // 20,
        "instructions": 0,
        "verification": max_chars // 8,
        "repo_map": max_chars // 3,
        "git": max_chars // 6,
        "tree": max_chars // 6,
    }


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

    seen: set[Path] = set()
    seen_basenames: set[str] = set()
    files: list[ContextFile] = []
    for path in candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        basename = resolved.name
        if basename in INSTRUCTION_BASENAMES and basename in seen_basenames:
            continue
        seen.add(resolved)
        if basename in INSTRUCTION_BASENAMES:
            seen_basenames.add(basename)
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


_CTX_CACHE: TtlCache[tuple[str, bool, bool, bool, int], ProjectContext] = TtlCache(120.0, maxsize=8)


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
    key = (str(cwd_path), include_git, include_tree, include_repo_map, tree_max_entries)

    def build() -> ProjectContext:
        from kite.context.verify_hint import resolve_verification_command

        root = find_project_root(cwd_path)
        repo_map = ""
        if include_repo_map and build_repo_map is not None:
            repo_map = build_repo_map(root, max_chars=4_000)
        verify_cmd, verify_src = resolve_verification_command(root)
        # The repo map already carries structure; a full tree on top of it is
        # duplicate directory info on every request — shrink it when both exist.
        tree_entries = tree_max_entries if not repo_map else min(tree_max_entries, 48)
        return ProjectContext(
            root=root,
            cwd=cwd_path,
            files=discover_agents_files(cwd_path),
            git_status=git_status_snippet(cwd_path) if include_git else "",
            tree_snippet=tree_snippet(root, max_entries=tree_entries) if include_tree else "",
            repo_map=repo_map,
            verification_command=verify_cmd,
            verification_source=verify_src,
        )

    return _CTX_CACHE.get_or_set(key, build)
