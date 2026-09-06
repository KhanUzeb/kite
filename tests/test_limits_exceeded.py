"""Step/cost budget LimitsExceeded messaging."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import LimitsExceeded
from kite.agent.loop import DefaultAgent
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry


class _StubModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def query(self, messages):
        raise AssertionError("should not query after limit")


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
