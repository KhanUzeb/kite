"""Agent completion discipline — no early submit, idle stall, error stop."""

from __future__ import annotations

import pytest

from kite.agent.loop import _MAX_IDLE_TURNS, DefaultAgent, _allow_text_submit
from kite.agent.mode import AgentMode


class _TextOnlyModel:
    def __init__(self, content: str = "I finished the refactor.") -> None:
        self.content = content

    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
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


def test_build_interactive_blocks_task_prose_submit() -> None:
    assert not _allow_text_submit("I finished the refactor.", mode=AgentMode.BUILD, interactive=True)
    assert _allow_text_submit("Hey! 👋", mode=AgentMode.BUILD, interactive=True, last_user="hi")


def test_interactive_build_does_not_early_submit_on_prose() -> None:
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    agent.messages = [{"role": "user", "content": "run the test suite"}]
    agent.execute_actions(
        {"role": "assistant", "content": "All tests pass. Task complete.", "extra": {"actions": []}}
    )
    assert agent._consecutive_no_tool_turns == 1
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Submit blocked" in blob or "claims" in blob.lower()


def test_changed_unverified_idle_does_not_stall() -> None:
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    agent.verification.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    for _ in range(_MAX_IDLE_TURNS + 1):
        agent.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "verification" in blob.lower()


def test_idle_turns_stall_without_more_queries() -> None:
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    for _ in range(_MAX_IDLE_TURNS):
        agent.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    assert agent.messages[-1].get("extra", {}).get("exit_status") == "Stalled"


def test_run_stops_on_error_without_raising(monkeypatch) -> None:
    agent = DefaultAgent(_BoomModel(), _StubEnv(), interactive=False, mode=AgentMode.BUILD, provider_max_retries=1)
    monkeypatch.setattr("kite.models.retry.is_transient_provider_error", lambda _e: False)
    result = agent.run("do something")
    assert result.get("exit_status") == "Error"
    assert "provider exploded" in str(result.get("error"))
