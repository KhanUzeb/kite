"""Mandatory approval — high-risk actions always prompt, no mode bypass."""

from __future__ import annotations

from pathlib import Path

from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.approval import (
    ApprovalPolicy,
    is_mandatory_approval,
    mandatory_approval_reason,
    needs_approval,
    prompt_approval,
)


def test_mandatory_git_commit_in_workspace(workspace: Path) -> None:
    ws = str(workspace)
    assert is_mandatory_approval(
        "bash",
        command="git commit -m 'wip'",
        workspace_cwd=ws,
        bash_cwd=ws,
    )
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="git commit -m 'wip'",
        workspace_cwd=ws,
        bash_cwd=ws,
    )
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.YOLO,
        command="git commit -m 'wip'",
        workspace_cwd=ws,
        bash_cwd=ws,
    )


def test_mandatory_pip_install_in_workspace(workspace: Path) -> None:
    ws = str(workspace)
    assert mandatory_approval_reason(
        "bash",
        command="pip install requests",
        workspace_cwd=ws,
        bash_cwd=ws,
    ) == "package installs always need approval"


def test_mandatory_rm(workspace: Path) -> None:
    reason = mandatory_approval_reason("bash", command="rm -rf node_modules")
    assert reason == "destructive file removal always needs approval"


def test_mandatory_bash_outside_workspace(workspace: Path) -> None:
    reason = mandatory_approval_reason(
        "bash",
        command="ls -la",
        workspace_cwd=str(workspace),
        bash_cwd="/tmp",
    )
    assert reason == "shell outside the project workspace always needs approval"


def test_mandatory_write_outside_workspace(workspace: Path) -> None:
    reason = mandatory_approval_reason(
        "write",
        arguments={"path": "/etc/passwd"},
        workspace_cwd=str(workspace),
    )
    assert "outside" in (reason or "")


def test_safe_bash_not_mandatory(workspace: Path) -> None:
    ws = str(workspace)
    assert not is_mandatory_approval(
        "bash",
        command="git status",
        workspace_cwd=ws,
        bash_cwd=ws,
    )
    assert not is_mandatory_approval(
        "bash",
        command="pytest -q",
        workspace_cwd=ws,
        bash_cwd=ws,
    )


def test_mandatory_skips_remembered_pattern(monkeypatch) -> None:
    from kite.ui.approval import action_pattern

    policy = ApprovalPolicy(session_patterns={"bash:git commit*"})
    pattern = action_pattern("bash", {"command": "git commit -m x"})
    assert policy.remembered(pattern)

    calls: list[str] = []

    def _ask(*_a, **_k) -> str:
        calls.append("asked")
        return "n"

    monkeypatch.setattr("kite.ui.approval.Prompt.ask", _ask)

    class _Console:
        def print(self, *_a, **_k) -> None:
            pass

    decision = prompt_approval(
        _Console(),  # type: ignore[arg-type]
        "bash",
        {"command": "git commit -m x"},
        reason="git history changes always need approval",
        policy=policy,
        mandatory=True,
    )
    assert calls == ["asked"]
    assert decision == "deny"

    calls.clear()
    decision2 = prompt_approval(
        _Console(),  # type: ignore[arg-type]
        "bash",
        {"command": "git commit -m x"},
        policy=policy,
        mandatory=False,
    )
    assert calls == []
    assert decision2 == "allow"
