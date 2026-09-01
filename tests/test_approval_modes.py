"""Approval modes — supervised/auto/yolo aliases and gating."""

from __future__ import annotations

from pathlib import Path

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name, parse_approval_mode
from kite.ui.approval import needs_approval


def test_approval_aliases() -> None:
    assert parse_approval_mode("supervised") is ApprovalMode.APPROVE
    assert parse_approval_mode("yolo") is ApprovalMode.YOLO
    assert approval_display_name(ApprovalMode.APPROVE) == "supervised"
    assert approval_display_name(ApprovalMode.YOLO) == "yolo"


def test_yolo_never_gates(workspace: Path) -> None:
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.YOLO,
        command="git commit -m x",
        workspace_cwd=str(workspace),
    )


def test_auto_mode_still_asks_for_git_commit() -> None:
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="git commit -m 'wip'",
    )


def test_auto_mode_does_not_gate_git_status() -> None:
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="git status",
    )


def test_auto_mode_gates_pip_install() -> None:
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="pip install requests",
    )


def test_auto_mode_allows_write_in_workspace(workspace: Path) -> None:
    assert not needs_approval(
        "write",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        arguments={"path": "src/foo.py"},
        workspace_cwd=str(workspace),
    )
