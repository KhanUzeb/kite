"""Parallel tool batching — path-disjoint reads and writes."""

from __future__ import annotations

from kite.agent.parallel import (
    action_parallel_eligible,
    actions_conflict,
    can_parallelize_batch,
    coalesce_crew_calls,
    paths_overlap,
    plan_execution_batches,
)


def test_paths_overlap_and_disjoint_writes(tmp_path) -> None:
    assert paths_overlap("/proj/src", "/proj/src/foo.py")
    assert not paths_overlap("/proj/a.py", "/proj/b.py")

    cwd = str(tmp_path)
    actions = [
        {"tool": "write", "arguments": {"path": "a.py", "content": "a"}},
        {"tool": "write", "arguments": {"path": "b.py", "content": "b"}},
    ]
    assert can_parallelize_batch(actions, cwd=cwd)
    assert plan_execution_batches(actions, cwd=cwd) == [actions]


def test_write_conflicts_same_and_overlapping(tmp_path) -> None:
    cwd = str(tmp_path)
    left = {"tool": "write", "arguments": {"path": "same.py", "content": "a"}}
    right = {"tool": "edit", "arguments": {"path": "same.py", "old": "a", "new": "b"}}
    assert actions_conflict(left, right, cwd=cwd)

    read = {"tool": "read", "arguments": {"path": "src/foo.py"}}
    write = {"tool": "write", "arguments": {"path": "src/foo.py", "content": "x"}}
    assert actions_conflict(read, write, cwd=cwd)

    grep = {"tool": "grep", "arguments": {"pattern": "x", "path": "src"}}
    child_write = {"tool": "write", "arguments": {"path": "src/foo.py", "content": "x"}}
    assert actions_conflict(grep, child_write, cwd=cwd)


def test_disjoint_read_write_and_mixed_batches(tmp_path) -> None:
    cwd = str(tmp_path)
    disjoint = [
        {"tool": "read", "arguments": {"path": "a.py"}},
        {"tool": "write", "arguments": {"path": "b.py", "content": "x"}},
    ]
    assert can_parallelize_batch(disjoint, cwd=cwd)

    mixed = [
        {"tool": "read", "arguments": {"path": "a.py"}},
        {"tool": "read", "arguments": {"path": "b.py"}},
        {"tool": "write", "arguments": {"path": "c.py", "content": "new"}},
    ]
    assert can_parallelize_batch(mixed, cwd=cwd)
    assert action_parallel_eligible("write")


def test_bash_splits_batches(tmp_path) -> None:
    cwd = str(tmp_path)
    actions = [
        {"tool": "read", "arguments": {"path": "a.py"}},
        {"tool": "bash", "arguments": {"command": "pytest -q"}},
        {"tool": "read", "arguments": {"path": "b.py"}},
    ]
    batches = plan_execution_batches(actions, cwd=cwd)
    assert batches == [
        [{"tool": "read", "arguments": {"path": "a.py"}}],
        [{"tool": "bash", "arguments": {"command": "pytest -q"}}],
        [{"tool": "read", "arguments": {"path": "b.py"}}],
    ]


def _sub(prompt: str, **kwargs) -> dict:
    return {"tool": "subagent", "arguments": {"prompt": prompt, **kwargs}}


def test_coalesce_sibling_subagents_into_crew(tmp_path) -> None:
    cwd = str(tmp_path)
    actions = [
        _sub("scan auth", label="auth", profile="scout"),
        _sub("scan billing", label="billing"),
        {"tool": "read", "arguments": {"path": "a.py"}},
    ]
    merged = coalesce_crew_calls(actions)
    assert len(merged) == 2
    crew = merged[0]
    assert crew["tool"] == "subagent"
    assert crew["arguments"]["prompts"] == ["scan auth", "scan billing"]
    assert crew["arguments"]["labels"] == ["auth", "billing"]
    assert crew["arguments"]["profiles"] == ["scout", ""]
    # One serial batch (the crew parallelizes inside the orchestrator).
    batches = plan_execution_batches(actions, cwd=cwd)
    assert len(batches) == 2 and batches[0] == [crew]


def test_coalesce_respects_async_collect_and_mismatch() -> None:
    assert coalesce_crew_calls([_sub("a", background=True), _sub("b")]) == [
        _sub("a", background=True),
        _sub("b"),
    ]
    assert coalesce_crew_calls([_sub("a"), _sub("b", wait_for=["x"])]) == [
        _sub("a"),
        _sub("b", wait_for=["x"]),
    ]
    assert coalesce_crew_calls([_sub("a"), _sub("b", prompts=["x", "y"])]) == [
        _sub("a"),
        _sub("b", prompts=["x", "y"]),
    ]
    # Different parent scope: never merge.
    no_merge = coalesce_crew_calls([_sub("a", parent_id="p1"), _sub("b", parent_id="p2")])
    assert len(no_merge) == 2
    # Non-adjacent subagents merge per run, not across other tools.
    split = coalesce_crew_calls([_sub("a"), {"tool": "bash", "arguments": {"command": "x"}}, _sub("b")])
    assert len(split) == 3
