"""Workspace execution context — project root vs session cwd."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from kite.context.discovery import find_project_root


class ExecutionMode(str, Enum):
    RESTRICTED = "restricted"
    HOST = "host"


@dataclass
class WorkspaceContext:
    """Separates repository context from the active shell/file cwd."""

    project_root: Path
    execution_cwd: Path
    initial_cwd: Path
    roots: tuple[Path, ...] = ()
    execution_mode: ExecutionMode = ExecutionMode.HOST

    @classmethod
    def discover(
        cls,
        cwd: str | Path,
        *,
        execution_mode: ExecutionMode | str = ExecutionMode.HOST,
        extra_roots: list[str] | None = None,
    ) -> WorkspaceContext:
        resolved = Path(cwd).expanduser().resolve()
        project_root = find_project_root(resolved)
        mode = ExecutionMode(execution_mode) if isinstance(execution_mode, str) else execution_mode
        roots: list[Path] = [project_root]
        for raw in extra_roots or []:
            try:
                roots.append(Path(raw).expanduser().resolve())
            except OSError:
                continue
        unique_roots = tuple(dict.fromkeys(roots))
        return cls(
            project_root=project_root,
            execution_cwd=resolved,
            initial_cwd=resolved,
            roots=unique_roots,
            execution_mode=mode,
        )

    def render_for_prompt(self) -> str:
        lines = [
            "## Execution context",
            f"- execution_mode: {self.execution_mode.value}",
            f"- project_root: {self.project_root}",
            f"- execution_cwd: {self.execution_cwd}",
            "- navigation: use set_cwd (or bash cwd=) when the user names a directory or work is outside execution_cwd",
        ]
        if self.execution_cwd != self.project_root:
            lines.append("- note: execution cwd differs from project root")
        if len(self.roots) > 1:
            lines.append("- workspace_roots:")
            for root in self.roots:
                lines.append(f"  - {root}")
        lines.append(
            "- verification: checks are scoped per package in monorepos; override via .kite/verification.toml"
        )
        return "\n".join(lines)


class ExecutionSession:
    """Mutable session cwd — updated by set_cwd and bash cwd args."""

    def __init__(self, workspace: WorkspaceContext):
        self.workspace = workspace
        self._cwd = workspace.execution_cwd

    @property
    def execution_cwd(self) -> Path:
        return self._cwd

    @property
    def project_root(self) -> Path:
        return self.workspace.project_root

    def resolve_path(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self._cwd / p
        return p.resolve()

    def set_cwd(self, path: str | Path) -> tuple[Path | None, str]:
        try:
            target = self.resolve_path(path)
        except OSError as e:
            return None, f"invalid path: {e}"
        if not target.is_dir():
            return None, f"not a directory: {target}"
        self._cwd = target
        return target, ""
