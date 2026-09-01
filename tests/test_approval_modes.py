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


def test_supervised_gates_all_mutations(workspace: Path) -> None:
    assert needs_approval(
        "write",
        AgentMode.BUILD,
        ApprovalMode.APPROVE,
        arguments={"path": "src/foo.py"},
        workspace_cwd=str(workspace),
    )
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.APPROVE,
        command="git status",
        workspace_cwd=str(workspace),
    )


def test_supervised_allows_reads() -> None:
    assert not needs_approval("read", AgentMode.BUILD, ApprovalMode.APPROVE)
    assert not needs_approval("grep", AgentMode.BUILD, ApprovalMode.APPROVE)


def test_auto_mode_allows_git_commit_in_workspace(workspace: Path) -> None:
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="git commit -m 'wip'",
        workspace_cwd=str(workspace),
        bash_cwd=str(workspace),
    )


def test_auto_mode_gates_git_commit_outside_workspace(workspace: Path) -> None:
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="git commit -m 'wip'",
        workspace_cwd=str(workspace),
        bash_cwd="/tmp",
    )


def test_auto_mode_allows_pip_install_in_workspace(workspace: Path) -> None:
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="pip install requests",
        workspace_cwd=str(workspace),
        bash_cwd=str(workspace),
    )


def test_auto_mode_allows_write_in_workspace(workspace: Path) -> None:
    assert not needs_approval(
        "write",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        arguments={"path": "src/foo.py"},
        workspace_cwd=str(workspace),
    )


def test_auto_mode_gates_write_outside_workspace(workspace: Path) -> None:
    assert needs_approval(
        "write",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        arguments={"path": "/etc/passwd"},
        workspace_cwd=str(workspace),
    )
