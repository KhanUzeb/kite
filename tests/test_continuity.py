"""Continuity briefs, budget auto-continue, memory opt-in, compaction episodes."""

from __future__ import annotations

from kite.config.interactive_budget import effective_agent_limits, resolve_interactive_limits
from kite.config.runtime import AgentRuntimeConfig, MemoryConfig
from kite.memory.continuity import (
    build_continuity_brief,
    format_continuity_section,
    latest_continuity_markdown,
    next_budget_action,
    record_continuity_after_compact,
    save_continuity,
    should_budget_auto_continue,
)
from kite.memory.store import MemoryStore
from kite.prompts import assemble_system_prompt
from kite.ui.budget_continue import decide_budget_continue


def test_build_continuity_brief_includes_mission_and_todos() -> None:
    brief = build_continuity_brief(
        messages=[{"role": "user", "content": "Add auth tests"}],
        todos=[{"status": "in_progress", "content": "write failing test"}],
        task="Add auth tests",
    )
    md = brief.to_markdown()
    assert "Add auth tests" in md
    assert "write failing test" in md


def test_should_budget_auto_continue_caps_and_inbox() -> None:
    assert should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
    assert not should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=True,
    )


def test_next_budget_action() -> None:
    assert (
        next_budget_action(
            exit_status="LimitsExceeded",
            continues_used=0,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=1,
            inbox_queued=False,
        )
        == "continue"
    )


def test_record_continuity_after_compact(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    md = record_continuity_after_compact(
        store=store,
        messages=[
            {"role": "user", "content": "Ship the fix"},
            {"role": "assistant", "content": "Patched src/app.py"},
        ],
        todos=[{"status": "in_progress", "content": "add regression test"}],
        session_id="sess1",
        cwd=str(workspace),
        task="Ship the fix",
    )
    assert "## Continuity" in md
    loaded = latest_continuity_markdown(store, session_id="sess1")
    assert "Ship the fix" in loaded


def test_decide_budget_continue_yes() -> None:
    assert (
        decide_budget_continue(
            exit_status="LimitsExceeded",
            continues_used=0,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=2,
            inbox_queued=False,
        )
        == "continue"
    )


def test_decide_budget_continue_stop_at_cap() -> None:
    assert (
        decide_budget_continue(
            exit_status="LimitsExceeded",
            continues_used=2,
            max_continues=2,
            todos=[{"status": "pending", "content": "x"}],
            tool_call_count=2,
            inbox_queued=False,
        )
        == "stop"
    )


def test_default_assemble_omits_durable_memory(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    store.remember("prefer ruff", scope="project")
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    system = assemble_system_prompt(config=cfg, memory="", continuity="")
    assert "# Memory" not in system
    assert "prefer ruff" not in system


def test_assemble_includes_memory_when_passed(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    store.remember("prefer ruff", scope="project")
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    memory = store.render_for_prompt()
    system = assemble_system_prompt(config=cfg, memory=memory, continuity="")
    assert "# Memory" in system
    assert "prefer ruff" in system


def test_continuity_section_is_not_memory_block() -> None:
    section = format_continuity_section("## Continuity\n- Mission: ship fix")
    assert "Working continuity" in section
    assert "# Memory" not in section
    assert "ship fix" in section


def test_save_continuity_does_not_pin_by_default(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    brief = build_continuity_brief(
        messages=[{"role": "user", "content": "Fix auth"}],
        todos=[{"status": "pending", "content": "test"}],
        task="Fix auth",
    )
    brief.paths = ["src/auth.py"]
    save_continuity(store=store, brief=brief, session_id="s1", cwd=str(workspace))
    assert not store.notes(scope="project")


def test_interactive_floors_on_package_defaults() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=40,
        user_cost=5.0,
        runtime_step=40,
        runtime_cost=5.0,
    )
    assert steps == 80
    assert cost == 10.0


def test_honor_explicit_lower_user_caps() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=20,
        user_cost=1.0,
        runtime_step=20,
        runtime_cost=1.0,
    )
    assert steps == 20
    assert cost == 1.0


def test_effective_agent_limits_long_task() -> None:
    steps, cost = effective_agent_limits(
        interactive=False,
        options_step=None,
        options_cost=None,
        runtime_step=40,
        runtime_cost=5.0,
        user_step=40,
        user_cost=5.0,
        interactive_step=80,
        interactive_cost=10.0,
        long_task=True,
    )
    assert steps == 120
    assert cost == 25.0