"""Fluid working rhythm — soft long-term context, separate from weighted memory."""

from __future__ import annotations

from kite.config.runtime import AgentRuntimeConfig, MemoryConfig
from kite.memory.store import MemoryStore
from kite.memory.working_style import (
    append_signal,
    format_working_section,
    infer_style_signals,
    observe_session_turn,
    read_signals,
    render_working_context,
    working_path,
)
from kite.prompts import assemble_system_prompt


def test_infer_style_signals_soft_phrasing() -> None:
    rows = infer_style_signals(mode="plan", write_edits=5, bash_calls=4)
    assert rows
    assert all("often" in s or "comfortable" in s or "iterates" in s or "sketches" in s for s in rows)


def test_working_file_append_and_render(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    append_signal("prefers small focused diffs")
    assert "prefers small focused diffs" in read_signals()
    assert working_path().is_file()

    rendered = render_working_context(store)
    assert "Working rhythm" in rendered
    assert "prefers small focused diffs" in rendered
    assert "untrusted" in rendered.lower() or "working rhythm" in rendered.lower()


def test_observe_session_turn_records_style(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    added = observe_session_turn(
        store,
        session_id="s1",
        mode="plan",
        approval="readonly",
        extra={"exit_status": "Submitted", "model_stats": {"write_edits": 6, "bash_calls": 1}},
    )
    assert added >= 1
    episodes = [e for e in store.episodes(limit=10) if e.kind == "style"]
    assert episodes


def test_working_rhythm_in_system_prompt_without_memory_opt_in(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    append_signal("likes to steer mid-run")
    working = render_working_context(store)
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    system = assemble_system_prompt(config=cfg, memory="", working_style=working, continuity="")
    assert "Working rhythm" in system
    assert "steer mid-run" in system
    assert "# Memory" not in system


def test_format_working_section_is_distinct_from_memory() -> None:
    section = format_working_section("### Signals\n- tends to plan first")
    assert "Working rhythm" in section
    assert "# Memory" not in section
    assert "tends to plan first" in section
    assert "untrusted" in section.lower()
