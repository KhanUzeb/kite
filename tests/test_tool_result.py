"""ToolResult and tool metadata tests."""

from __future__ import annotations

from kite.agent.tool_result import ToolResult
from kite.env.local import LocalEnvironment
from kite.tools import Tool, ToolRegistry
from kite.tools.metadata import metadata_for


def test_tool_result_roundtrip():
    raw = {
        "ok": True,
        "output": "hello",
        "path": "/tmp/x",
        "metadata": {"duration_ms": 12},
    }
    result = ToolResult.from_dict(raw)
    again = ToolResult.from_dict(result.to_dict())
    assert again.ok is True
    assert again.output == "hello"
    assert again.data.get("path") == "/tmp/x"


def test_tool_result_normalize_adds_summary(workspace):
    env = LocalEnvironment(cwd=str(workspace))
    out = env.execute({"tool": "read", "arguments": {"path": str(workspace / "src" / "app.py")}})
    assert out["ok"] is True
    assert out.get("summary")
    assert out.get("metadata", {}).get("tool") == "read"


def test_tool_metadata_defaults():
    read_meta = metadata_for("read")
    assert read_meta.read_only is True
    assert read_meta.concurrency_safe is True
    bash_meta = metadata_for("bash")
    assert bash_meta.mutating is True
    assert bash_meta.cancellable is True


def test_tool_exposes_metadata():
    tool = Tool("read", "read file", {"type": "object", "properties": {}}, lambda _a: {"ok": True})
    assert tool.metadata.read_only is True


def test_registry_metadata_lookup():
    reg = ToolRegistry([Tool("grep", "grep", {"type": "object", "properties": {}}, lambda _a: {"ok": True})])
    tool = reg.get("grep")
    assert tool is not None
    assert tool.metadata.concurrency_safe is True
