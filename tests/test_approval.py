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


def test_git_reads_skip_approval() -> None:
    """Read-only git bash never prompts (any approval mode)."""
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git status"
    )
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git log -1"
    )
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git -C /tmp/repo branch"
    )


def test_git_writes_require_approval() -> None:
    """Mutating git bash always prompts."""
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git commit -m wip"
    )
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git push origin main"
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
