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


def _c_test_paths_overlap_and_disjoint_writes(tmp_path) -> None:
    assert paths_overlap("/proj/src", "/proj/src/foo.py")
    assert not paths_overlap("/proj/a.py", "/proj/b.py")

    cwd = str(tmp_path)
    actions = [
        {"tool": "write", "arguments": {"path": "a.py", "content": "a"}},
        {"tool": "write", "arguments": {"path": "b.py", "content": "b"}},
    ]
    assert can_parallelize_batch(actions, cwd=cwd)
    assert plan_execution_batches(actions, cwd=cwd) == [actions]


def _c_test_write_conflicts_same_and_overlapping(tmp_path) -> None:
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


def _c_test_disjoint_read_write_and_mixed_batches(tmp_path) -> None:
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


def _c_test_batching_preserves_model_call_order(tmp_path) -> None:
    """Concurrency must never reorder calls the model sequenced deliberately.

    A tighter packer exists (first-fit turns [write A, read B, write C, read A]
    into 2 batches instead of 3) but it hoists later calls ahead of earlier
    ones. The runtime cannot tell an independent call from a dependent one, so
    "read the config -> run with it -> read the result" must stay sequential.
    """
    cwd = str(tmp_path)

    def a(tool, path):
        return {"tool": tool, "arguments": {"path": path}}

    staggered = [a("write", "A.py"), a("read", "B.py"), a("write", "C.py"), a("read", "A.py")]
    batches = plan_execution_batches(staggered, cwd=cwd)
    flat = [act for batch in batches for act in batch]
    assert flat == staggered, "calls execute in the order the model emitted them"
    # The read of A.py must not be hoisted ahead of the write of A.py.
    read_a = next(i for i, x in enumerate(flat) if x["arguments"]["path"] == "A.py" and x["tool"] == "read")
    write_a = next(i for i, x in enumerate(flat) if x["arguments"]["path"] == "A.py" and x["tool"] == "write")
    assert read_a > write_a

    # Independent disjoint calls still batch into a single round-trip.
    reads = [a("read", f"f{i}.py") for i in range(4)]
    assert plan_execution_batches(reads, cwd=cwd) == [reads]

    # No call means no batch, rather than a batch holding nothing.
    assert plan_execution_batches([], cwd=cwd) == []


def _c_test_bash_splits_batches(tmp_path) -> None:
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


def _c_test_coalesce_sibling_subagents_into_crew(tmp_path) -> None:
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


def _c_test_coalesce_respects_async_collect_and_mismatch() -> None:
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


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_paths_overlap_and_disjoint_writes, test_write_conflicts_same_and_overlapping, test_disjoint_read_write_and_mixed_batches."""
    _t0 = tmp_path / "t0_0"
    _t0.mkdir(parents=True, exist_ok=True)
    _c_test_paths_overlap_and_disjoint_writes(tmp_path=_t0)
    _t1 = tmp_path / "t0_1"
    _t1.mkdir(parents=True, exist_ok=True)
    _c_test_write_conflicts_same_and_overlapping(tmp_path=_t1)
    _t2 = tmp_path / "t0_2"
    _t2.mkdir(parents=True, exist_ok=True)
    _c_test_disjoint_read_write_and_mixed_batches(tmp_path=_t2)

def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_batching_preserves_model_call_order, test_bash_splits_batches."""
    _t0 = tmp_path / "t1_0"
    _t0.mkdir(parents=True, exist_ok=True)
    _c_test_batching_preserves_model_call_order(tmp_path=_t0)
    _t1 = tmp_path / "t1_1"
    _t1.mkdir(parents=True, exist_ok=True)
    _c_test_bash_splits_batches(tmp_path=_t1)

def test_batch_02(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_coalesce_sibling_subagents_into_crew, test_coalesce_respects_async_collect_and_mismatch."""
    _t0 = tmp_path / "t2_0"
    _t0.mkdir(parents=True, exist_ok=True)
    _c_test_coalesce_sibling_subagents_into_crew(tmp_path=_t0)
    _c_test_coalesce_respects_async_collect_and_mismatch()

