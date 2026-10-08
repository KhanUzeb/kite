"""Workspace discovery and host vs restricted execution cwd."""

from __future__ import annotations

from pathlib import Path

from kite.config.runtime import GuardrailConfig
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def test_workspace_discovery_preserves_nested_execution_cwd(workspace: Path) -> None:
    nested = workspace / "pkg"
    nested.mkdir()
    found = WorkspaceContext.discover(nested)
    assert found.project_root == workspace.resolve()
    assert found.execution_cwd == nested.resolve()


def test_host_and_restricted_modes_allow_external_reads(workspace: Path, tmp_path: Path) -> None:
    external = tmp_path / "data.txt"
    external.write_text("hello host\n", encoding="utf-8")
    for mode in (ExecutionMode.HOST, ExecutionMode.RESTRICTED):
        session = ExecutionSession(WorkspaceContext.discover(workspace, execution_mode=mode))
        env = LocalEnvironment(
            registry=ToolRegistry(
                make_coding_tools(
                    cwd=str(workspace),
                    guardrails=GuardrailPolicy(GuardrailConfig(execution_mode=mode.value), workspace, execution=session),
                    execution=session,
                    enabled=["read"],
                )
            )
        )
        out = env.execute({"tool": "read", "arguments": {"path": str(external)}})
        assert out["ok"] is True and "hello host" in out["output"], mode


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


def test_toolchain_scout_deduplicates_python_and_renders_versions(tmp_path, monkeypatch) -> None:
    """The model sees runnable interpreters/compilers with versions and paths."""
    import sys

    from kite.context import toolchains

    python = Path(sys.executable)
    node = tmp_path / "node"
    node.touch()
    candidates = {"python": python, "python3": python, "node": node}
    versions = {python: "Python 3.11.9", node: "v22.0.0"}
    monkeypatch.setattr(toolchains, "_CACHE", {})
    monkeypatch.setattr(toolchains, "_which", candidates.get)
    monkeypatch.setattr(toolchains, "_probe_version", lambda path, _flag: versions[path])
    monkeypatch.setattr("kite.env.venv.discover_venv", lambda *_roots: None)

    items = toolchains.scout_toolchains(tmp_path, tmp_path)
    assert [(item.name, item.source) for item in items] == [("python", "active"), ("node", "path")]
    section = toolchains.render_toolchains(items)
    assert "Python 3.11.9" in section and "node v22.0.0" in section
    assert str(python.absolute()) in section and str(node) in section

