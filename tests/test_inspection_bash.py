"""Read-only bash detection for plan mode and token-efficient inspection."""

from __future__ import annotations

from kite.guardrails.sandbox import is_inspection_bash


def test_inspection_bash_allows_rg_and_peek() -> None:
    assert is_inspection_bash("rg 'def foo' src/")
    assert is_inspection_bash("head -n 40 src/app.py")
    assert is_inspection_bash("wc -l README.md")
    assert is_inspection_bash("sed -n '10,30p' src/main.py")
    assert is_inspection_bash("cd pkg && rg error")


def test_inspection_bash_blocks_mutations() -> None:
    assert not is_inspection_bash("rm -rf build")
    assert not is_inspection_bash("git commit -m x")
    assert not is_inspection_bash("echo hi > out.txt")
    assert not is_inspection_bash("pip install requests")


def test_plan_mode_allows_inspection_bash(workspace, tmp_path) -> None:
    from kite.agent.loop import DefaultAgent
    from kite.agent.mode import AgentMode
    from kite.env.local import LocalEnvironment
    from kite.tools import ToolRegistry
    from kite.guardrails import GuardrailConfig, GuardrailPolicy
    from kite.tools.coding import make_coding_tools

    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=GuardrailPolicy(GuardrailConfig(), workspace),
        enabled=["bash"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    agent = DefaultAgent(object(), env, mode=AgentMode.PLAN)
    # echo is inspection-safe and works on Windows cmd + Unix shells
    action = {"tool": "bash", "arguments": {"command": "echo plan-peek-ok"}}
    out = agent._invoke_tool("bash", {"command": "echo plan-peek-ok"}, action)
    assert out.get("ok") is True
    assert "plan-peek-ok" in str(out.get("output") or "")


def test_plan_mode_blocks_mutating_bash(workspace) -> None:
    from kite.agent.loop import DefaultAgent
    from kite.agent.mode import AgentMode
    from kite.env.local import LocalEnvironment
    from kite.tools import ToolRegistry
    from kite.guardrails import GuardrailConfig, GuardrailPolicy
    from kite.tools.coding import make_coding_tools

    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=GuardrailPolicy(GuardrailConfig(), workspace),
        enabled=["bash"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    agent = DefaultAgent(object(), env, mode=AgentMode.PLAN)
    out = agent._invoke_tool("bash", {"command": "rm -rf build"}, {"tool": "bash", "arguments": {"command": "rm -rf build"}})
    assert out.get("ok") is False
    assert "plan mode" in str(out.get("output") or "").lower()
