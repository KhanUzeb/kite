"""Approval policy — trust mode and trusted_paths."""

from __future__ import annotations

from pathlib import Path

from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.approval import needs_approval


def test_trust_mode_allows_read_tools(workspace: Path) -> None:
    assert not needs_approval("read", AgentMode.BUILD, ApprovalMode.TRUST)


def test_trust_mode_blocks_destructive_bash(workspace: Path) -> None:
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.TRUST,
        command="rm -rf node_modules",
    )


def test_trusted_paths_skip_bash_approval(workspace: Path) -> None:
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.TRUST,
        command="pytest -q",
        trusted_paths=["src/"],
        workspace_cwd=str(workspace),
        bash_cwd=str(workspace / "src"),
    )
