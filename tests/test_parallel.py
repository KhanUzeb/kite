"""Parallel tool batching — path-disjoint reads and writes."""

from __future__ import annotations

from kite.agent.parallel import (
    action_parallel_eligible,
    actions_conflict,
    can_parallelize_batch,
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
