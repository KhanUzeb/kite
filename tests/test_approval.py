"""Approval policy — trust mode and trusted_paths."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.approval import make_approver, needs_approval


def test_trust_mode_allows_read_tools(workspace: Path) -> None:
    assert not needs_approval("read", AgentMode.BUILD, ApprovalMode.TRUST)


def test_trust_mode_blocks_destructive_bash(workspace: Path) -> None:
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.TRUST,
        command="rm -rf node_modules",
        workspace_cwd=str(workspace),
    )


def test_git_reads_skip_approval(workspace: Path) -> None:
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git status",
        workspace_cwd=str(workspace),
    )
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git log -1",
        workspace_cwd=str(workspace), bash_cwd=str(workspace),
    )


def test_git_writes_require_approval(workspace: Path) -> None:
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git commit -m wip",
        workspace_cwd=str(workspace),
    )
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git push origin main",
        workspace_cwd=str(workspace), bash_cwd=str(workspace),
    )


def test_git_status_pattern_does_not_cover_push() -> None:
    from kite.ui.approval import ApprovalPolicy, action_pattern

    policy = ApprovalPolicy(session_patterns={"bash:git*"})
    status = action_pattern("bash", {"command": "git status"})
    push = action_pattern("bash", {"command": "git push origin main"})
    commit = action_pattern("bash", {"command": "git commit -m x"})
    assert policy.remembered(status)
    assert not policy.remembered(push)
    assert not policy.remembered(commit)


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


def test_noninteractive_auto_denies_canonical_mandatory_actions(workspace: Path) -> None:
    approver = make_approver(
        Console(file=StringIO()),
        mode=AgentMode.BUILD,
        approval=ApprovalMode.AUTO,
        interactive=False,
        workspace_cwd=str(workspace),
    )

    assert approver("write", {"path": str(workspace / "inside.txt")}, {}) == "allow"
    assert approver("memory", {"action": "remember", "text": "secret"}, {}) == "deny"


def test_plan_readonly_approver_allows_inspection_bash(workspace: Path) -> None:
    approver = make_approver(
        Console(file=StringIO()),
        mode=AgentMode.PLAN,
        approval=ApprovalMode.READONLY,
        interactive=False,
        workspace_cwd=str(workspace),
    )

    assert approver("bash", {"command": "git status"}, {}) == "allow"


def test_readonly_denies_durable_memory_without_prompting(workspace: Path) -> None:
    coordinator = MagicMock()
    coordinator.request.return_value = "allow"
    approver = make_approver(
        Console(file=StringIO()),
        mode=AgentMode.BUILD,
        approval=ApprovalMode.READONLY,
        interactive=True,
        workspace_cwd=str(workspace),
        coordinator=coordinator,
    )

    assert approver("memory", {"action": "remember", "text": "secret"}, {}) == "deny"
    coordinator.request.assert_not_called()
