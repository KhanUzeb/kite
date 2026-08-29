"""Loop detection for repetitive tool calls."""

from __future__ import annotations

from kite.agent.loop_guard import LoopGuard


def test_bash_loops_warn_after_two_repeats() -> None:
    guard = LoopGuard(repeat_threshold=3)
    args = {"command": "ls"}
    assert guard.record("bash", args) is None
    warning = guard.record("bash", args)
    assert warning is not None
    assert "Loop detected" in warning
    assert "2 times" in warning


def test_non_bash_uses_higher_threshold() -> None:
    guard = LoopGuard(repeat_threshold=3)
    args = {"pattern": "foo"}
    assert guard.record("grep", args) is None
    assert guard.record("grep", args) is None
    warning = guard.record("grep", args)
    assert warning is not None
    assert "3 times" in warning
