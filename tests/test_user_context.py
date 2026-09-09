"""Global USER.md / PROFILE.md + subagent profile personas."""

from __future__ import annotations

import pytest

from kite.agent.subagent_profiles import (
    format_profile_trust,
    get_profile,
    init_user_profile,
    list_profiles,
    profiles_for_orchestrator,
    reload_profiles,
    resolve_subagent_task,
    user_profile_path,
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


def test_init_user_profile_writes_and_loads(kite_home) -> None:
    reload_profiles()
    path = init_user_profile(
        "my-auditor",
        label="Auditor",
        role="debugger",
        description="Security-focused review",
    )
    assert path == user_profile_path("my-auditor")
    assert path.is_file()
    prof = get_profile("my-auditor")
    assert prof is not None
    assert prof.label == "Auditor"
    assert prof.role == "debugger"
    assert format_profile_trust(prof) == "user-local"
    composed, role, label = resolve_subagent_task(prompt="check auth", profile="my-auditor")
    assert "check auth" in composed
    assert role == "debugger"
    assert label == "Auditor"
    assert "kite:untrusted" in composed


def test_init_user_profile_rejects_invalid_id(kite_home) -> None:
    with pytest.raises(ValueError, match="invalid profile id"):
        init_user_profile("!!!")


def test_kite_subagents_parser_registered() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["subagents", "--init", "reviewer-custom", "--role", "debugger"])
    assert args.command == "subagents"
    assert args.init == "reviewer-custom"
    assert args.role == "debugger"
