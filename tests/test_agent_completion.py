"""Agent completion discipline — no early submit, idle stall, error stop."""

from __future__ import annotations

import pytest

from kite.agent.loop import (
    DefaultAgent,
    _allow_text_submit,
    _is_casual_chat,
    _MAX_IDLE_TURNS,
)
from kite.agent.mode import AgentMode
from kite.agent.exceptions import Submitted


class _TextOnlyModel:
    def __init__(self, content: str = "I finished the refactor.") -> None:
        self.content = content
        self.calls = 0

    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
        self.calls += 1
        return {"role": "assistant", "content": self.content, "extra": {"actions": [], "cost": 0.0}}

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [{"role": "tool", "content": str(outputs)}]


class _BoomModel:
    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
        raise RuntimeError("provider exploded")

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return []


class _StubEnv:
    def execute(self, action: dict, cwd: str = "") -> dict:
        return {"ok": True, "output": ""}


def test_casual_chat_detection() -> None:
    assert _is_casual_chat("hi")
    assert _is_casual_chat("Thanks!")
    assert not _is_casual_chat("I finished the refactor and everything works now.")


def test_build_interactive_blocks_task_prose_submit() -> None:
    assert not _allow_text_submit(
        "I finished the refactor.",
        mode=AgentMode.BUILD,
        interactive=True,
    )
    assert _allow_text_submit("hi", mode=AgentMode.BUILD, interactive=True)


def test_build_non_interactive_never_text_submits() -> None:
    assert not _allow_text_submit("done", mode=AgentMode.BUILD, interactive=False)


def test_interactive_build_does_not_early_submit_on_prose() -> None:
    model = _TextOnlyModel("All tests pass. Task complete.")
    agent = DefaultAgent(
        model,
        _StubEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    with pytest.raises(Submitted):
        agent.execute_actions({"role": "assistant", "content": "hi", "extra": {"actions": []}})
    # task-like prose should nudge, not submit
    agent.execute_actions(
        {"role": "assistant", "content": "All tests pass. Task complete.", "extra": {"actions": []}}
    )
    assert agent._consecutive_no_tool_turns == 1
    assert any(m.get("role") == "user" for m in agent.messages)


def test_idle_turns_stall_without_more_queries() -> None:
    model = _TextOnlyModel("still planning…")
    agent = DefaultAgent(
        model,
        _StubEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    for _ in range(_MAX_IDLE_TURNS - 1):
        agent.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    agent.execute_actions({"role": "assistant", "content": "still thinking", "extra": {"actions": []}})
    assert agent.messages[-1].get("role") == "exit"
    assert agent.messages[-1].get("extra", {}).get("exit_status") == "Stalled"


def test_run_stops_on_error_without_raising(monkeypatch) -> None:
    agent = DefaultAgent(
        _BoomModel(),
        _StubEnv(),
        interactive=False,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    monkeypatch.setattr("kite.models.retry.is_transient_provider_error", lambda _e: False)
    result = agent.run("do something")
    assert result.get("exit_status") == "Error"
    assert "provider exploded" in str(result.get("error"))
    assert result.get("traceback")
