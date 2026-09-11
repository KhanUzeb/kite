"""Approval modes, consequence tiers, and non-interactive denials."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name, parse_approval_mode
from kite.ui.approval import (
    ApprovalPolicy,
    ConsequenceLevel,
    action_consequence,
    action_pattern,
    consequence_prompt_threshold,
    is_mandatory_approval,
    make_approver,
    mandatory_approval_reason,
    needs_approval,
    prompt_approval,
)


def test_aliases_trust_and_git_gating(workspace: Path) -> None:
    assert parse_approval_mode("supervised") is ApprovalMode.APPROVE
    assert parse_approval_mode("yolo") is ApprovalMode.YOLO
    assert approval_display_name(ApprovalMode.APPROVE) == "supervised"
    assert not needs_approval("read", AgentMode.BUILD, ApprovalMode.TRUST)
    assert not needs_approval("read", AgentMode.BUILD, ApprovalMode.APPROVE)
    assert needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.TRUST,
        command="rm -rf node_modules",
        workspace_cwd=str(workspace),
    )
    ws = str(workspace)
    assert not needs_approval("bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git status", workspace_cwd=ws)
    assert needs_approval("bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="git commit -m wip", workspace_cwd=ws)
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.YOLO, command="git commit -m x", workspace_cwd=ws, bash_cwd=ws
    )
    policy = ApprovalPolicy(session_patterns={"bash:git*"})
    assert policy.remembered(action_pattern("bash", {"command": "git status"}))
    assert not policy.remembered(action_pattern("bash", {"command": "git push origin main"}))
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.TRUST,
        command="pytest -q",
        trusted_paths=["src/"],
        workspace_cwd=ws,
        bash_cwd=str(workspace / "src"),
    )


def test_auto_and_supervised_mutations(workspace: Path) -> None:
    ws = str(workspace)
    assert needs_approval("write", AgentMode.BUILD, ApprovalMode.APPROVE, arguments={"path": "src/foo.py"}, workspace_cwd=ws)
    assert not needs_approval("write", AgentMode.BUILD, ApprovalMode.AUTO, arguments={"path": "src/foo.py"}, workspace_cwd=ws)
    assert needs_approval("write", AgentMode.BUILD, ApprovalMode.AUTO, arguments={"path": "/etc/passwd"}, workspace_cwd=ws)
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="pip install requests", workspace_cwd=ws, bash_cwd=ws
    )
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git commit -m wip", workspace_cwd=ws, bash_cwd=ws
    )
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="curl https://example.com", workspace_cwd=ws, bash_cwd=ws
    )
    assert needs_approval("bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git commit -m wip", workspace_cwd=ws, bash_cwd="/tmp")


def test_consequence_tiers_and_critical_gates(workspace: Path) -> None:
    ws = str(workspace)
    assert consequence_prompt_threshold(ApprovalMode.YOLO) is ConsequenceLevel.CRITICAL
    assert consequence_prompt_threshold(ApprovalMode.AUTO) is ConsequenceLevel.SERIOUS
    assert consequence_prompt_threshold(ApprovalMode.APPROVE) is ConsequenceLevel.ROUTINE
    level, _ = action_consequence("bash", command="pip install requests", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.ROUTINE
    level, _ = action_consequence("bash", command="git commit -m wip", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.ROUTINE
    level, reason = action_consequence("bash", command="git push origin main", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.CRITICAL and "blocked" in reason
    assert not is_mandatory_approval("bash", command="git commit -m wip", workspace_cwd=ws, bash_cwd=ws)
    assert mandatory_approval_reason("bash", command="pip install requests", workspace_cwd=ws, bash_cwd=ws) is None
    level, reason = action_consequence("bash", command="rm -rf node_modules", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.SERIOUS and "destructive" in reason
    assert not is_mandatory_approval("bash", command="rm -rf node_modules", workspace_cwd=ws, bash_cwd=ws)
    assert mandatory_approval_reason("bash", command="ls -la", workspace_cwd=ws, bash_cwd="/tmp") == (
        "shell outside the project workspace always needs approval"
    )
    assert "outside" in (mandatory_approval_reason("write", arguments={"path": "/etc/passwd"}, workspace_cwd=ws) or "")
    assert is_mandatory_approval("bash", command="sudo apt install foo", workspace_cwd=ws, bash_cwd=ws)
    assert not is_mandatory_approval("bash", command="git status", workspace_cwd=ws, bash_cwd=ws)
    for cmd in ("rmdir /s /q .pytest_cache", "rm -rf .pytest_cache"):
        assert not is_mandatory_approval("bash", command=cmd, workspace_cwd=ws, bash_cwd=ws), cmd
        assert not needs_approval("bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws), cmd
    assert needs_approval("bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="rmdir /s /q .pytest_cache", workspace_cwd=ws, bash_cwd=ws)


def test_yolo_auto_approve_routine_dev_commands(workspace: Path) -> None:
    ws = str(workspace)
    yolo = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.YOLO, interactive=False, workspace_cwd=ws)
    auto = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.AUTO, interactive=False, workspace_cwd=ws)
    for approver in (yolo, auto):
        assert approver("write", {"path": str(workspace / "inside.txt")}, {}) == "allow"
        assert approver("bash", {"command": "pip install -e .", "cwd": ws}, {}) == "allow"
        assert approver("bash", {"command": "pytest -q", "cwd": ws}, {}) == "allow"
        assert approver("bash", {"command": "git commit -m wip", "cwd": ws}, {}) == "allow"
    assert yolo("bash", {"command": "curl https://example.com", "cwd": ws}, {}) == "allow"
    assert auto("bash", {"command": "curl https://example.com", "cwd": ws}, {}) == "deny"
    assert yolo("bash", {"command": "sudo rm -rf /", "cwd": ws}, {}) == "deny"
    assert auto("memory", {"action": "remember", "text": "secret"}, {}) == "deny"


def test_noninteractive_auto_plan_and_readonly(workspace: Path) -> None:
    auto = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.AUTO, interactive=False, workspace_cwd=str(workspace))
    assert auto("write", {"path": str(workspace / "inside.txt")}, {}) == "allow"
    outside = workspace.parent / "outside"
    assert auto("bash", {"command": f'cd "{outside}" && echo escaped > escape.txt'}, {}) == "deny"
    assert auto("bash", {"command": f'cd "{workspace}" && echo inspected'}, {}) == "allow"
    plan = make_approver(Console(file=StringIO()), mode=AgentMode.PLAN, approval=ApprovalMode.READONLY, interactive=False, workspace_cwd=str(workspace))
    assert plan("bash", {"command": "git status"}, {}) == "allow"
    coordinator = MagicMock()
    coordinator.request.return_value = "allow"
    readonly = make_approver(
        Console(file=StringIO()),
        mode=AgentMode.BUILD,
        approval=ApprovalMode.READONLY,
        interactive=True,
        workspace_cwd=str(workspace),
        coordinator=coordinator,
    )
    assert readonly("memory", {"action": "remember", "text": "secret"}, {}) == "deny"
    coordinator.request.assert_not_called()


def test_mandatory_still_prompts_when_pattern_remembered(monkeypatch) -> None:
    policy = ApprovalPolicy(session_patterns={"bash:git commit*"})
    calls: list[str] = []
    monkeypatch.setattr("kite.ui.approval.Prompt.ask", lambda *_a, **_k: calls.append("asked") or "n")

    class _Console:
        def print(self, *_a, **_k) -> None:
            pass

    deny = prompt_approval(_Console(), "bash", {"command": "sudo rm -rf /"}, reason="privileged", policy=policy, mandatory=True)
    assert calls == ["asked"] and deny == "deny"
    calls.clear()
    allow = prompt_approval(_Console(), "bash", {"command": "git commit -m x"}, policy=policy, mandatory=False)
    assert calls == [] and allow == "allow"
