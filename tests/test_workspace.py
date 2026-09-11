"""Workspace discovery and host vs restricted execution cwd."""

from __future__ import annotations

from pathlib import Path

from kite.config.runtime import GuardrailConfig
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def test_workspace_defaults_and_discovery(workspace: Path) -> None:
    ctx = WorkspaceContext.discover(workspace)
    assert ctx.execution_mode is ExecutionMode.HOST
    assert GuardrailConfig().execution_mode == "host" and GuardrailConfig().host_access() is True
    nested = workspace / "pkg"
    nested.mkdir()
    found = WorkspaceContext.discover(nested)
    assert found.project_root == workspace.resolve()
    assert found.execution_cwd == nested.resolve()


def test_host_allows_external_read_restricted_blocks(workspace: Path, tmp_path: Path) -> None:
    external = tmp_path / "data.txt"
    external.write_text("hello host\n", encoding="utf-8")
    host = ExecutionSession(WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.HOST))
    host_env = LocalEnvironment(
        registry=ToolRegistry(
            make_coding_tools(
                cwd=str(workspace),
                guardrails=GuardrailPolicy(GuardrailConfig(execution_mode="host"), workspace, execution=host),
                execution=host,
                enabled=["read"],
            )
        )
    )
    out = host_env.execute({"tool": "read", "arguments": {"path": str(external)}})
    assert out["ok"] is True and "hello host" in out["output"]
    restricted = ExecutionSession(WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.RESTRICTED))
    rest_env = LocalEnvironment(
        registry=ToolRegistry(
            make_coding_tools(
                cwd=str(workspace),
                guardrails=GuardrailPolicy(GuardrailConfig(execution_mode="restricted"), workspace, execution=restricted),
                execution=restricted,
                enabled=["read"],
            )
        )
    )
    blocked = rest_env.execute({"tool": "read", "arguments": {"path": str(external)}})
    assert blocked["ok"] is False and blocked.get("blocked") is True


def test_set_cwd_updates_session_and_can_leave_project(workspace: Path, tmp_path: Path) -> None:
    sub = workspace / "pkg"
    sub.mkdir()
    session = ExecutionSession(WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.RESTRICTED))
    env = LocalEnvironment(
        registry=ToolRegistry(
            make_coding_tools(
                cwd=str(workspace),
                guardrails=GuardrailPolicy(GuardrailConfig(), workspace, execution=session),
                execution=session,
                enabled=["set_cwd", "read"],
            )
        )
    )
    moved = env.execute({"tool": "set_cwd", "arguments": {"path": "pkg"}})
    assert moved["ok"] is True and session.execution_cwd == sub.resolve()
    external = tmp_path / "desktop_sim"
    external.mkdir()
    (external / "note.txt").write_text("outside project\n", encoding="utf-8")
    left = env.execute({"tool": "set_cwd", "arguments": {"path": str(external)}})
    assert left["ok"] is True
    read = env.execute({"tool": "read", "arguments": {"path": "note.txt"}})
    assert read["ok"] is True and "outside project" in read["output"]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    host = ExecutionSession(WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.HOST))
    target, err = host.set_cwd(elsewhere)
    assert err == "" and target == elsewhere.resolve()
