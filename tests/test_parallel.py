"""Parallel tool batching — path-disjoint reads and writes."""

from __future__ import annotations

from kite.agent.parallel import (
    action_parallel_eligible,
    actions_conflict,
    can_parallelize_batch,
    paths_overlap,
    plan_execution_batches,
)


def test_paths_overlap_prefix() -> None:
    assert paths_overlap("/proj/src", "/proj/src/foo.py")
    assert not paths_overlap("/proj/a.py", "/proj/b.py")


def test_disjoint_writes_parallel(tmp_path) -> None:
    cwd = str(tmp_path)
    actions = [
        {"tool": "write", "arguments": {"path": "a.py", "content": "a"}},
        {"tool": "write", "arguments": {"path": "b.py", "content": "b"}},
    ]
    assert can_parallelize_batch(actions, cwd=cwd)
    assert plan_execution_batches(actions, cwd=cwd) == [actions]


def test_same_path_writes_conflict(tmp_path) -> None:
    cwd = str(tmp_path)
    left = {"tool": "write", "arguments": {"path": "same.py", "content": "a"}}
    right = {"tool": "edit", "arguments": {"path": "same.py", "old": "a", "new": "b"}}
    assert actions_conflict(left, right, cwd=cwd)


def test_read_and_write_disjoint_paths(tmp_path) -> None:
    cwd = str(tmp_path)
    actions = [
        {"tool": "read", "arguments": {"path": "a.py"}},
        {"tool": "write", "arguments": {"path": "b.py", "content": "x"}},
    ]
    assert can_parallelize_batch(actions, cwd=cwd)


def test_read_and_write_overlapping_paths_conflict(tmp_path) -> None:
    cwd = str(tmp_path)
    left = {"tool": "read", "arguments": {"path": "src/foo.py"}}
    right = {"tool": "write", "arguments": {"path": "src/foo.py", "content": "x"}}
    assert actions_conflict(left, right, cwd=cwd)


def test_grep_dir_and_write_child_conflict(tmp_path) -> None:
    cwd = str(tmp_path)
    left = {"tool": "grep", "arguments": {"pattern": "x", "path": "src"}}
    right = {"tool": "write", "arguments": {"path": "src/foo.py", "content": "x"}}
    assert actions_conflict(left, right, cwd=cwd)


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


def test_mixed_read_write_batch(tmp_path) -> None:
    cwd = str(tmp_path)
    actions = [
        {"tool": "read", "arguments": {"path": "a.py"}},
        {"tool": "read", "arguments": {"path": "b.py"}},
        {"tool": "write", "arguments": {"path": "c.py", "content": "new"}},
    ]
    assert can_parallelize_batch(actions, cwd=cwd)
    assert action_parallel_eligible("write")
