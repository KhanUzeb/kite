"""Durable memory is opt-in; continuity is working state."""

from __future__ import annotations

from kite.config.runtime import AgentRuntimeConfig, MemoryConfig
from kite.memory.continuity import format_continuity_section, save_continuity, build_continuity_brief
from kite.memory.store import MemoryStore
from kite.prompts import assemble_system_prompt


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
