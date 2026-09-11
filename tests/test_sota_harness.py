"""Repo map and SOTA harness feature tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from kite.agent.loop import DefaultAgent
from kite.agent.mode import AgentMode, tools_for_mode
from kite.agent.verification import VerificationCollector
from kite.application.execution import build_tool_executor
from kite.env.local import LocalEnvironment
from kite.eval import ReplayBundle, run_replay
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def test_submit_tool_requires_message(workspace: Path) -> None:
    tools = make_coding_tools(cwd=str(workspace), enabled=["submit"])
    submit = next(t for t in tools if t.name == "submit")
    out = submit.run({})
    assert not out.get("ok")
    assert "message required" in str(out.get("error") or "")


def test_submit_in_build_tools() -> None:
    enabled = [
        "bash", "read", "write", "edit", "grep", "glob", "ls", "submit",
        "todo_write", "todo_read", "task",
    ]
    build = tools_for_mode(AgentMode.BUILD, enabled)
    assert "submit" in build
    assert "submit" not in tools_for_mode(AgentMode.PLAN, enabled)


def test_verification_collector_evidence_in_summary(tmp_path: Path) -> None:
    # Use an isolated temp dir — scanning system /tmp can hit PermissionError
    # on CI runners (e.g. snap-private-tmp under ubuntu-latest).
    vc = VerificationCollector(workspace_root=str(tmp_path), run_id="run-ev")
    vc.on_tool_end(
        "bash",
        {"command": "pytest -q"},
        {"ok": True, "returncode": 0, "output": "3 passed"},
    )
    summary = vc.summary()
    assert summary.get("evidence", {}).get("status") == "verified"
    assert summary["evidence"]["passed"] >= 1


def test_replay_acceptance_checks() -> None:
    bundle = ReplayBundle(
        run_id="acc-1",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "Done — html updated."}],
        events=[{"kind": "verification_status", "payload": {"status": "verified"}}],
        acceptance={
            "content_contains": "html updated",
            "content_excludes": "pytest",
            "min_events": 1,
            "event_kinds": ["verification_status"],
        },
    )
    out = run_replay(bundle)
    assert out["ok"]
    assert out["acceptance"]["ok"]


def test_replay_acceptance_failure() -> None:
    bundle = ReplayBundle(
        run_id="acc-2",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "nope"}],
        acceptance={"content_contains": "expected phrase"},
    )
    out = run_replay(bundle)
    assert not out["ok"]
    assert out["acceptance"]["failures"]


def test_loop_uses_tool_executor_policy_block(workspace: Path) -> None:
    tools = make_coding_tools(cwd=str(workspace), enabled=["read"])
    env = LocalEnvironment(cwd=str(workspace), registry=ToolRegistry(tools))
    executor = build_tool_executor(
        workspace_root=workspace,
        execution_mode="restricted",
        no_guardrails=False,
        runner=lambda call: env.execute({"tool": call.name, "arguments": dict(call.arguments)}),
    )
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    agent = DefaultAgent(MagicMock(), env, tool_executor=executor)
    out = agent._run_gated_via_executor(
        "read",
        {"path": "../outside.txt"},
        {"tool": "read", "arguments": {"path": "../outside.txt"}},
    )
    assert out.get("blocked") or not out.get("ok")
    assert "outside" in str(out.get("error") or out.get("output") or "").lower()


def test_loop_denies_required_approval_without_approver(workspace: Path) -> None:
    calls: list[str] = []
    executor = build_tool_executor(
        workspace_root=workspace,
        execution_mode="host",
        no_guardrails=False,
        runner=lambda call: calls.append(call.name) or {"ok": True, "output": "executed"},
    )
    agent = DefaultAgent(MagicMock(), MagicMock(), tool_executor=executor)
    target = workspace.parent / "outside.txt"

    out = agent._run_gated_via_executor(
        "write",
        {"path": str(target), "content": "blocked"},
        {"tool": "write", "arguments": {"path": str(target), "content": "blocked"}},
    )

    assert out.get("blocked") is True
    assert "approval required" in str(out.get("error") or out.get("output") or "")
    assert calls == []


def test_legacy_tool_path_denies_mutation_without_approver() -> None:
    environment = MagicMock()
    environment.execute.return_value = {"ok": True, "output": "executed"}
    agent = DefaultAgent(MagicMock(), environment, tool_executor=None)

    out = agent._run_gated(
        "write",
        {"path": "outside.txt", "content": "blocked"},
        {"tool": "write", "arguments": {"path": "outside.txt", "content": "blocked"}},
    )

    assert out.get("blocked") is True
    assert "approval required" in str(out.get("error") or out.get("output") or "")
    environment.execute.assert_not_called()


def test_executor_tool_path_allows_inspection_without_approver(workspace: Path) -> None:
    calls: list[str] = []
    executor = build_tool_executor(
        workspace_root=workspace,
        execution_mode="host",
        no_guardrails=False,
        runner=lambda call: calls.append(call.name) or {"ok": True, "output": "clean"},
    )
    agent = DefaultAgent(MagicMock(), MagicMock(), tool_executor=executor, mode=AgentMode.PLAN)

    out = agent._run_gated_via_executor(
        "bash",
        {"command": "git status"},
        {"tool": "bash", "arguments": {"command": "git status"}},
    )

    assert out.get("ok") is True
    assert calls == ["bash"]
