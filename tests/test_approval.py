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


def test_approve_mode_does_not_gate_git_reads() -> None:
    for cmd in (
        "git status",
        "git log -1 --oneline",
        "git diff HEAD",
        "git -C /tmp/repo branch",
        "git stash list",
    ):
        assert not needs_approval(
            "bash",
            AgentMode.BUILD,
            ApprovalMode.APPROVE,
            command=cmd,
        ), f"expected read-only: {cmd}"


def test_approve_mode_gates_git_writes() -> None:
    for cmd in (
        "git add .",
        "git commit -m wip",
        "git push origin main",
        "git pull",
        "git checkout main",
        "git branch -d old",
        "git stash pop",
    ):
        assert needs_approval(
            "bash",
            AgentMode.BUILD,
            ApprovalMode.APPROVE,
            command=cmd,
        ), f"expected write gate: {cmd}"


def test_git_bash_kind_classification() -> None:
    from kite.ui.approval import git_bash_kind

    assert git_bash_kind("git status -sb") == "read"
    assert git_bash_kind("git add src/") == "write"
    assert git_bash_kind("git fetch origin") == "write"
    assert git_bash_kind("pytest -q") == "other"


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
