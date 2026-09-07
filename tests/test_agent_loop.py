"""Agent loop limits, provider retry, loop guard."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import LimitsExceeded, ProviderFault
from kite.agent.loop import DefaultAgent
from kite.agent.loop_guard import LoopGuard
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry


class _StubModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def query(self, messages):
        raise AssertionError("should not query after limit")


class _FlakyModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def __init__(self) -> None:
        self.calls = 0

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def query(self, messages):
        self.calls += 1
        if self.calls < 3:
            raise TimeoutError("connection timed out")
        return {
            "role": "assistant",
            "content": "done",
            "extra": {"cost": 0.0},
        }


# --- limits ---


def test_query_raises_limits_exceeded_with_step_detail() -> None:
    model = _StubModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        step_limit=2,
        cost_limit=5.0,
    )
    agent.n_calls = 2
    agent.messages = [model.format_message("user", content="hi")]
    with pytest.raises(LimitsExceeded) as ei:
        agent.query()
    msg = ei.value.messages[0]
    assert msg["extra"]["exit_status"] == "LimitsExceeded"
    assert msg["extra"].get("limit_kind") == "steps"
    assert "step" in str(msg.get("content") or "").lower()
    assert msg["content"] != "LimitsExceeded"


def test_query_raises_limits_exceeded_with_cost_detail() -> None:
    model = _StubModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        step_limit=40,
        cost_limit=1.0,
    )
    agent.cost = 1.0
    agent.messages = [model.format_message("user", content="hi")]
    with pytest.raises(LimitsExceeded) as ei:
        agent.query()
    msg = ei.value.messages[0]
    assert msg["extra"].get("limit_kind") == "cost"
    assert "cost" in str(msg.get("content") or "").lower() or "$" in str(msg.get("content") or "")


# --- provider retry in loop ---


def test_query_retries_transient_errors() -> None:
    events: list[str] = []
    model = _FlakyModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        provider_max_retries=4,
        step_limit=1,
        on_event=lambda e: events.append(e.kind),
    )
    agent.messages = [
        model.format_message("system", content="sys"),
        model.format_message("user", content="hi"),
    ]
    msg = agent.query()
    assert msg["content"] == "done"
    assert model.calls == 3
    assert "provider_retry" in events


def test_query_raises_provider_fault_after_exhaustion() -> None:
    model = _FlakyModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        provider_max_retries=2,
    )
    agent.messages = [model.format_message("user", content="hi")]
    with pytest.raises(ProviderFault):
        agent.query()


# --- loop guard ---


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
