"""Loop detection for repetitive tool calls."""

from __future__ import annotations

from kite.agent.loop_guard import LoopGuard


def test_bash_loops_warn_after_two_repeats() -> None:
    guard = LoopGuard(repeat_threshold=3)
    args = {"command": "ls"}
    assert guard.record("bash", args).warning is None
    warning = guard.record("bash", args)
    assert warning.warning is not None
    assert "same arguments" in warning.warning
    assert "2 times" in warning.warning


def test_non_bash_uses_higher_threshold() -> None:
    guard = LoopGuard(repeat_threshold=3)
    args = {"pattern": "foo"}
    assert guard.record("grep", args).warning is None
    assert guard.record("grep", args).warning is None
    warning = guard.record("grep", args)
    assert warning.warning is not None
    assert "3 times" in warning.warning


def test_progress_reset_on_different_output() -> None:
    guard = LoopGuard(repeat_threshold=3, hard_threshold=5)
    args = {"command": "curl -s localhost/status"}
    guard.record("bash", args, {"ok": True, "output": "pending"})
    guard.record("bash", args, {"ok": True, "output": "pending"})
    third = guard.record("bash", args, {"ok": True, "output": "ready"})
    assert third.warning is None


def test_hard_stop_after_many_repeats() -> None:
    guard = LoopGuard(repeat_threshold=2, hard_threshold=4)
    args = {"command": "ls"}
    for _ in range(3):
        guard.record("bash", args, {"ok": True, "output": "same"})
    hard = guard.record("bash", args, {"ok": True, "output": "same"})
    assert hard.hard_stop is not None
    assert "hard-stop" in hard.hard_stop.lower()
