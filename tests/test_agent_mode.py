"""Plan / build mode tool allowlists and prompt assembly."""

from __future__ import annotations

from kite.agent.mode import (
    BUILD_TOOLS,
    MUTATING_TOOLS,
    PLAN_TOOLS,
    READONLY_TOOLS,
    AgentMode,
    tools_for_mode,
    tools_for_nested_subagent,
)
from kite.prompts import load_prompt_template


def test_plan_tools_exclude_write_edit() -> None:
    assert "write" not in PLAN_TOOLS
    assert "edit" not in PLAN_TOOLS
    assert "todo_write" in PLAN_TOOLS
    assert "bash" in PLAN_TOOLS
    assert "task" in PLAN_TOOLS
    assert "subagent" in PLAN_TOOLS
    for name in ("read", "grep", "glob", "ls", "todo_read"):
        assert name in PLAN_TOOLS


def test_plan_tools_are_readonly_plus_checklist_and_bash() -> None:
    assert READONLY_TOOLS <= PLAN_TOOLS
    assert PLAN_TOOLS - READONLY_TOOLS == frozenset({"todo_write", "bash"})
    assert {"write", "edit", "bash"} <= MUTATING_TOOLS


def test_nested_subagent_tools_exclude_subagent() -> None:
    enabled = ["read", "grep", "subagent", "task", "bash", "todo_write", "memory"]
    nested = tools_for_nested_subagent(enabled)
    assert "subagent" not in nested
    assert "memory" not in nested
    assert "read" in nested
    assert "grep" in nested


def test_tools_for_mode_filters_enabled() -> None:
    enabled = ["read", "write", "edit", "bash", "todo_write", "grep", "task"]
    plan = tools_for_mode(AgentMode.PLAN, enabled)
    assert plan == ["read", "bash", "todo_write", "grep", "task"]
    assert "write" not in plan
    assert "edit" not in plan

    build = tools_for_mode(AgentMode.BUILD, enabled)
    assert set(build) == set(enabled)
    expected_min = (PLAN_TOOLS - {"bash"}) | MUTATING_TOOLS | {"todo_write"}
    assert expected_min <= BUILD_TOOLS


def test_mode_plan_prompt_has_loop_and_forbids_mutate() -> None:
    plan = load_prompt_template("mode_plan")
    assert "## Working loop" in plan
    assert "Explore" in plan
    assert "Structure" in plan
    assert "todo_write" in plan
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in plan
    assert "/build" in plan
    lower = plan.lower()
    assert "write" in lower and "edit" in lower
    assert "task" in lower or "subagent" in lower
    assert "risk" in lower


def test_mode_build_prompt_picks_up_checklist() -> None:
    build = load_prompt_template("mode_build")
    assert "Checklist handoff" in build
    assert "plan" in build.lower()
    assert "Don't start a checklist" in build


def test_plan_mode_blocks_submit_as_done(workspace) -> None:
    from kite.agent.loop import DefaultAgent
    from kite.env.local import LocalEnvironment
    from kite.guardrails import GuardrailConfig, GuardrailPolicy
    from kite.tools import ToolRegistry
    from kite.tools.coding import make_coding_tools

    tools = make_coding_tools(
        cwd=str(workspace),
        guardrails=GuardrailPolicy(GuardrailConfig(), workspace),
        enabled=["bash"],
    )
    env = LocalEnvironment(registry=ToolRegistry(tools))
    agent = DefaultAgent(object(), env, mode=AgentMode.PLAN)
    cmd = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    out = agent._invoke_tool("bash", {"command": cmd}, {"tool": "bash", "arguments": {"command": cmd}})
    assert out.get("ok") is False
    assert "plan mode" in str(out.get("output") or "").lower()
