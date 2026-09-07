"""Agent provider retry loop."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import ProviderFault
from kite.agent.loop import DefaultAgent
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry


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
