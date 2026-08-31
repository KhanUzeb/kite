"""Workspace context and host/restricted execution mode tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.config.runtime import GuardrailConfig
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def test_workspace_context_discovers_project_root(workspace: Path):
    nested = workspace / "pkg"
    nested.mkdir()
    ctx = WorkspaceContext.discover(nested)
    assert ctx.project_root == workspace.resolve()
    assert ctx.execution_cwd == nested.resolve()


def test_execution_session_set_cwd(workspace: Path, tmp_path: Path):
    external = tmp_path / "elsewhere"
    external.mkdir()
    ctx = WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.HOST)
    session = ExecutionSession(ctx)
    target, err = session.set_cwd(external)
    assert err == ""
    assert target == external.resolve()
    assert session.execution_cwd == external.resolve()


def test_host_mode_allows_external_read(workspace: Path, tmp_path: Path):
    external = tmp_path / "data.txt"
    external.write_text("hello host\n", encoding="utf-8")
    ctx = WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.HOST)
    session = ExecutionSession(ctx)
    guard = GuardrailPolicy(
        GuardrailConfig(execution_mode="host"),
        workspace,
        execution=session,
    )
    tools = make_coding_tools(cwd=str(workspace), guardrails=guard, execution=session, enabled=["read"])
    env = LocalEnvironment(registry=ToolRegistry(tools))
    out = env.execute({"tool": "read", "arguments": {"path": str(external)}})
    assert out["ok"] is True
    assert "hello host" in out["output"]


def test_restricted_mode_blocks_external_read(workspace: Path, tmp_path: Path):
    external = tmp_path / "data.txt"
    external.write_text("nope\n", encoding="utf-8")
    ctx = WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.RESTRICTED)
    session = ExecutionSession(ctx)
    guard = GuardrailPolicy(GuardrailConfig(execution_mode="restricted"), workspace, execution=session)
    tools = make_coding_tools(cwd=str(workspace), guardrails=guard, execution=session, enabled=["read"])
    env = LocalEnvironment(registry=ToolRegistry(tools))
    out = env.execute({"tool": "read", "arguments": {"path": str(external)}})
    assert out["ok"] is False
    assert out.get("blocked") is True


def test_set_cwd_tool_updates_session(workspace: Path, tmp_path: Path):
    sub = workspace / "pkg"
    sub.mkdir()
    ctx = WorkspaceContext.discover(workspace, execution_mode=ExecutionMode.RESTRICTED)
    session = ExecutionSession(ctx)
    guard = GuardrailPolicy(GuardrailConfig(), workspace, execution=session)
    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=guard,
        execution=session,
        enabled=["set_cwd", "read"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    out = env.execute({"tool": "set_cwd", "arguments": {"path": "pkg"}})
    assert out["ok"] is True
    assert session.execution_cwd == sub.resolve()
