"""Global USER.md / PROFILE.md + subagent profile personas."""

from __future__ import annotations

from kite.agent.subagent_profiles import (
    get_profile,
    list_profiles,
    profiles_for_orchestrator,
    resolve_subagent_task,
)
from kite.config.runtime import AgentRuntimeConfig, MemoryConfig
from kite.memory.store import MemoryStore
from kite.memory.user_context import (
    append_profile_note,
    append_user_note,
    profile_path,
    read_profile,
    read_user,
    render_user_context,
    user_path,
)
from kite.prompts import assemble_system_prompt


def test_user_and_profile_paths_are_global(kite_home) -> None:
    assert user_path().name == "USER.md"
    assert profile_path().name == "PROFILE.md"
    assert user_path().parent.name == "memory"
    assert user_path().parent == profile_path().parent


def test_append_user_and_profile_notes(kite_home) -> None:
    append_user_note("prefers pytest")
    append_profile_note("Python backend focus")
    assert "prefers pytest" in read_user()
    assert "Python backend focus" in read_profile()


def test_render_user_context_includes_working(workspace, kite_home) -> None:
    from kite.memory.working_style import append_signal

    store = MemoryStore.open(workspace)
    append_user_note("timezone UTC")
    append_signal("likes small diffs")
    rendered = render_user_context(store)
    assert "User" in rendered
    assert "timezone UTC" in rendered
    assert "Working rhythm" in rendered
    assert "small diffs" in rendered


def test_user_context_in_system_prompt_without_memory_opt_in(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    append_user_note("name: Ada")
    ctx = render_user_context(store)
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    system = assemble_system_prompt(config=cfg, memory="", working_style=ctx, continuity="")
    assert "name: Ada" in system
    assert "# Memory" not in system


def test_bundled_subagent_profiles_load() -> None:
    profiles = list_profiles()
    ids = {p.id for p in profiles}
    assert "scout" in ids
    assert "coder" in ids


def test_resolve_subagent_task_with_profile() -> None:
    composed, role, label = resolve_subagent_task(
        prompt="find auth module",
        profile="scout",
        role="",
        label="",
    )
    assert "scout" in composed.lower() or "Scout" in composed
    assert "find auth module" in composed
    assert role == "architect"
    assert label == "Scout"


def test_profiles_for_orchestrator_catalog() -> None:
    catalog = profiles_for_orchestrator()
    assert "scout" in catalog
    assert "profile" in catalog.lower() or "persona" in catalog.lower()


def test_get_profile_unknown() -> None:
    assert get_profile("nonexistent-xyz") is None
