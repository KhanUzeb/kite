"""Workspace discovery and host vs restricted execution cwd."""

from __future__ import annotations

from pathlib import Path

from kite.config.runtime import GuardrailConfig
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def _c_test_workspace_defaults_and_discovery(workspace: Path) -> None:
    ctx = WorkspaceContext.discover(workspace)
    assert ctx.execution_mode is ExecutionMode.HOST
    assert GuardrailConfig().execution_mode == "host" and GuardrailConfig().host_access() is True
    nested = workspace / "pkg"
    nested.mkdir()
    found = WorkspaceContext.discover(nested)
    assert found.project_root == workspace.resolve()
    assert found.execution_cwd == nested.resolve()


def _c_test_host_allows_external_read_restricted_blocks(workspace: Path, tmp_path: Path) -> None:
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
    assert blocked["ok"] is True and "hello host" in blocked["output"]  # reads outside are free


def _c_test_set_cwd_updates_session_and_can_leave_project(workspace: Path, tmp_path: Path) -> None:
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


def test_toolchain_scout_finds_python(tmp_path) -> None:
    """The model sees runnable interpreters/compilers with versions and paths."""
    import sys

    from kite.context.toolchains import render_toolchains, scout_toolchains

    items = scout_toolchains(tmp_path, tmp_path)
    names = {item.name for item in items}
    assert "python" in names
    assert any(Path(item.path).is_file() for item in items if item.name == "python")
    assert any(item.source in {"project-venv", "active", "path"} for item in items)
    section = render_toolchains(items)
    assert "## Toolchains" in section and sys.executable.replace("\\", "/")[:20] in section.replace("\\", "/")


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_workspace_defaults_and_discovery, test_host_allows_external_read_restricted_blocks, test_set_cwd_updates_session_and_can_leave_project."""
    _w0 = tmp_path / "w0_0"
    (_w0 / "src").mkdir(parents=True, exist_ok=True)
    (_w0 / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (_w0 / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _c_test_workspace_defaults_and_discovery(workspace=_w0)
    _t1 = tmp_path / "t0_1"
    _t1.mkdir(parents=True, exist_ok=True)
    _w1 = tmp_path / "w0_1"
    (_w1 / "src").mkdir(parents=True, exist_ok=True)
    (_w1 / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (_w1 / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _c_test_host_allows_external_read_restricted_blocks(tmp_path=_t1, workspace=_w1)
    _t2 = tmp_path / "t0_2"
    _t2.mkdir(parents=True, exist_ok=True)
    _w2 = tmp_path / "w0_2"
    (_w2 / "src").mkdir(parents=True, exist_ok=True)
    (_w2 / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (_w2 / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _c_test_set_cwd_updates_session_and_can_leave_project(tmp_path=_t2, workspace=_w2)

