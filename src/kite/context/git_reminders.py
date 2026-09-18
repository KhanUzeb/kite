"""Git workspace reminders for agents (branch discipline, worktrees)."""

from __future__ import annotations

from pathlib import Path

from kite.context.project_init import default_branch, is_git_workspace


def worktree_reminder_markdown(root: Path) -> str:
    if not is_git_workspace(root):
        return ""
    branch = default_branch(root)
    return (
        "<worktree-reminder>\n"
        "This workspace is a git repository.\n"
        f"- Do not commit directly to `{branch}` unless the user explicitly requires it.\n"
        "- Before creating a worktree, run `git worktree list` and reuse a matching worktree when possible.\n"
        "- Read project instructions (AGENTS.md / KITE.md) before broad tracked-file edits.\n"
        "- Read-only exploration does not require a new branch or worktree.\n"
        "</worktree-reminder>"
    )
