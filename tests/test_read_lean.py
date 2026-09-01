"""Lean read tool output — no line numbers unless requested."""

from __future__ import annotations

from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry
from kite.guardrails import GuardrailConfig, GuardrailPolicy
from kite.tools.coding import make_coding_tools


def test_read_default_without_line_numbers(workspace) -> None:
    src = workspace / "sample.txt"
    src.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=GuardrailPolicy(GuardrailConfig(), workspace),
        enabled=["read"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    out = env.execute({"tool": "read", "arguments": {"path": "sample.txt"}})
    assert out.get("ok") is True
    body = str(out.get("output") or "")
    assert "alpha" in body
    assert "|alpha" not in body


def test_read_numbered_when_requested(workspace) -> None:
    src = workspace / "sample.txt"
    src.write_text("one\n", encoding="utf-8")
    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=GuardrailPolicy(GuardrailConfig(), workspace),
        enabled=["read"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    out = env.execute({"tool": "read", "arguments": {"path": "sample.txt", "numbered": True}})
    body = str(out.get("output") or "")
    assert "|one" in body
