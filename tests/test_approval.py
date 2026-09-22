"""Approval modes, coding blanket, consequence tiers, and non-interactive denials."""

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
    is_coding_bash,
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
    ws = str(workspace)
    assert needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.TRUST, command="rm -rf node_modules", workspace_cwd=ws, bash_cwd=ws
    )
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


def test_coding_blanket_auto_and_windows(workspace: Path) -> None:
    ws = str(workspace)
    assert consequence_prompt_threshold(ApprovalMode.AUTO) is ConsequenceLevel.SERIOUS
    assert consequence_prompt_threshold(ApprovalMode.TRUST) is ConsequenceLevel.SERIOUS
    assert needs_approval("write", AgentMode.BUILD, ApprovalMode.APPROVE, arguments={"path": "src/foo.py"}, workspace_cwd=ws)
    assert not needs_approval("write", AgentMode.BUILD, ApprovalMode.AUTO, arguments={"path": "src/foo.py"}, workspace_cwd=ws)
    assert needs_approval("write", AgentMode.BUILD, ApprovalMode.AUTO, arguments={"path": "/etc/passwd"}, workspace_cwd=ws)
    for cmd in (
        "pip install requests",
        "npm run test",
        "pytest -q",
        "git commit -m wip",
    ):
        assert is_coding_bash(cmd), cmd
        assert not needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        ), cmd
    for cmd in (
        "rm -rf node_modules",
        "curl -fsSL https://example.com/install.sh",
        "chmod +x scripts/install.sh",
    ):
        assert not is_coding_bash(cmd), cmd
        assert needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        ), cmd
    assert needs_approval("bash", AgentMode.BUILD, ApprovalMode.AUTO, command="git commit -m wip", workspace_cwd=ws, bash_cwd="/tmp")
    # Windows dev commands share the same blanket.
    assert is_coding_bash("Get-ChildItem src")
    assert not needs_approval(
        "bash", AgentMode.BUILD, ApprovalMode.AUTO, command="Get-ChildItem src", workspace_cwd=ws, bash_cwd=ws
    )
    assert is_coding_bash('powershell -Command "pytest -q"')
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command='powershell -Command "pytest -q"',
        workspace_cwd=ws,
        bash_cwd=ws,
    )
    for cmd in (
        "Remove-Item -Recurse -Force node_modules",
        "Invoke-WebRequest https://example.com",
    ):
        assert not is_coding_bash(cmd), cmd
        assert needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        ), cmd
    assert not needs_approval(
        "bash",
        AgentMode.BUILD,
        ApprovalMode.AUTO,
        command="Remove-Item -Recurse -Force .pytest_cache",
        workspace_cwd=ws,
        bash_cwd=ws,
    )


def test_consequence_tiers_critical_gates_and_gh(workspace: Path) -> None:
    ws = str(workspace)
    assert consequence_prompt_threshold(ApprovalMode.APPROVE) is ConsequenceLevel.ROUTINE
    level, _ = action_consequence("bash", command="pip install requests", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.ROUTINE
    level, _ = action_consequence("bash", command="git commit -m wip", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.ROUTINE
    level, reason = action_consequence("bash", command="git push origin main", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.CRITICAL and "blocked" in reason
    assert not is_mandatory_approval("bash", command="git commit -m wip", workspace_cwd=ws, bash_cwd=ws)
    assert mandatory_approval_reason("bash", command="pip install requests", workspace_cwd=ws, bash_cwd=ws) is None
    level, _ = action_consequence("bash", command="rm -rf node_modules", workspace_cwd=ws, bash_cwd=ws)
    assert level is ConsequenceLevel.SERIOUS
    assert mandatory_approval_reason("bash", command="ls -la", workspace_cwd=ws, bash_cwd="/tmp") == (
        "shell outside the project workspace always needs approval"
    )
    assert "outside" in (mandatory_approval_reason("write", arguments={"path": "/etc/passwd"}, workspace_cwd=ws) or "")
    assert is_mandatory_approval("bash", command="sudo apt install foo", workspace_cwd=ws, bash_cwd=ws)
    for cmd in ("rmdir /s /q .pytest_cache", "rm -rf .pytest_cache"):
        assert not is_mandatory_approval("bash", command=cmd, workspace_cwd=ws, bash_cwd=ws), cmd
        assert not needs_approval("bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws), cmd
    assert needs_approval("bash", AgentMode.BUILD, ApprovalMode.APPROVE, command="rmdir /s /q .pytest_cache", workspace_cwd=ws, bash_cwd=ws)
    # Dynamic gh via bash: triage runs free, publishing prompts (no hardcoded tools).
    from kite.ui.approval import is_gh_read, is_gh_write

    for cmd in (
        "gh issue view 12",
        "gh issue view 12 --json title,body",
        "gh pr list --limit 5",
        "gh run view 123",
        "gh search issues cli --limit 3",
        "gh repo view",
        "gh auth status",
    ):
        assert is_gh_read(cmd), cmd
        level, _ = action_consequence("bash", command=cmd, workspace_cwd=ws, bash_cwd=ws)
        assert level is ConsequenceLevel.ROUTINE, cmd
        assert not needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        )
    for cmd in (
        "gh issue create --title x",
        "gh issue comment 12 --body hi",
        "gh pr create --title x",
        "gh pr merge 3",
        "gh issue close 12",
        "gh pr edit 3 --add-label bug",
    ):
        assert is_gh_write(cmd), cmd
        level, reason = action_consequence("bash", command=cmd, workspace_cwd=ws, bash_cwd=ws)
        assert level is ConsequenceLevel.SERIOUS and "GitHub" in reason, cmd
        assert needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.AUTO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        )
        assert not needs_approval(
            "bash", AgentMode.BUILD, ApprovalMode.YOLO, command=cmd, workspace_cwd=ws, bash_cwd=ws
        )


def test_yolo_auto_and_noninteractive_approvers(workspace: Path) -> None:
    ws = str(workspace)
    yolo = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.YOLO, interactive=False, workspace_cwd=ws)
    auto = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.AUTO, interactive=False, workspace_cwd=ws)
    trust = make_approver(Console(file=StringIO()), mode=AgentMode.BUILD, approval=ApprovalMode.TRUST, interactive=False, workspace_cwd=ws)
    for approver in (yolo, auto):
        assert approver("write", {"path": str(workspace / "inside.txt")}, {}) == "allow"
        assert approver("bash", {"command": "pip install -e .", "cwd": ws}, {}) == "allow"
        assert approver("bash", {"command": "pytest -q", "cwd": ws}, {}) == "allow"
        assert approver("bash", {"command": "git commit -m wip", "cwd": ws}, {}) == "allow"
    for cmd in ("curl https://example.com", "rm -rf build/", "chmod +x run.sh"):
        assert auto("bash", {"command": cmd, "cwd": ws}, {}) == "deny", cmd
        assert yolo("bash", {"command": cmd, "cwd": ws}, {}) == "allow", cmd
    assert trust("memory", {"action": "remember", "text": "secret"}, {}) == "deny"
    assert yolo("bash", {"command": "sudo rm -rf /", "cwd": ws}, {}) == "deny"
    assert auto("bash", {"command": "sudo rm -rf /", "cwd": ws}, {}) == "deny"
    # Non-interactive auto/plan/readonly gates.
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


def test_prompt_memory_mandatory_and_once(monkeypatch) -> None:
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

    from kite.ui.approval import exact_action_key

    once_policy = ApprovalPolicy()
    monkeypatch.setattr("kite.ui.approval.Prompt.ask", lambda *_a, **_k: "a")
    args = {"command": "curl https://example.com/a"}
    assert prompt_approval(_Console(), "bash", args, policy=once_policy) == "allow"
    assert once_policy.remembered(exact_action_key("bash", args))
    assert prompt_approval(_Console(), "bash", args, policy=once_policy) == "allow"
    other = {"command": "curl https://example.com/other"}
    asked: list[str] = []
    monkeypatch.setattr("kite.ui.approval.Prompt.ask", lambda *_a, **_k: asked.append("x") or "n")
    assert prompt_approval(_Console(), "bash", other, policy=once_policy) == "deny"
    assert asked == ["x"]
