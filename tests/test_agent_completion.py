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
    assert _is_casual_chat("hi kite")
    assert _is_casual_chat("Thanks!")
    assert not _is_casual_chat("I finished the refactor and everything works now.")
    assert not _is_casual_chat("lower number of tests")
    assert not _is_casual_chat("can you lower the number of tests but without breaking functionality")


def test_build_interactive_blocks_task_prose_submit() -> None:
    assert not _allow_text_submit(
        "I finished the refactor.",
        mode=AgentMode.BUILD,
        interactive=True,
    )
    assert _allow_text_submit(
        "Hey! 👋",
        mode=AgentMode.BUILD,
        interactive=True,
        last_user="hi",
    )
    assert not _allow_text_submit(
        "Hey! 👋",
        mode=AgentMode.BUILD,
        interactive=True,
        last_user="lower number of tests",
    )
    assert _allow_text_submit(
        "Hey! I'm Kite — ready to help.",
        mode=AgentMode.BUILD,
        interactive=True,
        last_user="hi",
    )
    assert not _allow_text_submit(
        "Hey! I'm Kite — ready to help.",
        mode=AgentMode.BUILD,
        interactive=True,
        last_user="delete the pytest cache",
    )


def test_greeting_only_reply_does_not_submit_on_task_request() -> None:
    model = _TextOnlyModel("Hey! 👋")
    agent = DefaultAgent(
        model,
        _StubEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    agent.messages = [{"role": "user", "content": "lower number of tests"}]
    agent.execute_actions(
        {
            "role": "assistant",
            "content": model.content,
            "extra": {"actions": []},
        }
    )
    assert agent._consecutive_no_tool_turns == 1
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "No tool calls" in blob


def test_greeting_reply_submits_without_idle_nudge() -> None:
    model = _TextOnlyModel("Hey! 👋 I'm Kite — ready to help with code, tests, or docs.")
    agent = DefaultAgent(
        model,
        _StubEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    agent.messages = [{"role": "user", "content": "hi"}]
    agent.add_messages(
        {
            "role": "assistant",
            "content": model.content,
            "extra": {"actions": []},
        }
    )
    with pytest.raises(Submitted):
        agent.execute_actions(
            {
                "role": "assistant",
                "content": model.content,
                "extra": {"actions": []},
            }
        )
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "No tool calls" not in blob


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
    agent.messages = [{"role": "user", "content": "run the test suite"}]
    agent.execute_actions(
        {"role": "assistant", "content": "All tests pass. Task complete.", "extra": {"actions": []}}
    )
    assert agent._consecutive_no_tool_turns == 1
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Submit blocked" in blob or "claims" in blob.lower()
    assert any(m.get("role") == "user" for m in agent.messages)


def test_changed_unverified_idle_does_not_stall() -> None:
    model = _TextOnlyModel("I'll verify next.")
    agent = DefaultAgent(
        model,
        _StubEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    agent.verification.on_tool_end(
        "edit",
        {"path": "a.py"},
        {"ok": True, "path": "a.py", "diff": "d"},
    )
    assert agent.verification.status() == "changed_unverified"
    for _ in range(_MAX_IDLE_TURNS + 1):
        agent.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    assert agent.messages[-1].get("role") != "exit" or agent.messages[-1].get("extra", {}).get("exit_status") != "Stalled"
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "unverified edits" in blob.lower() or "verification" in blob.lower()


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


def test_run_from_worker_thread_skips_sigint(monkeypatch) -> None:
    """REPL turns run off the main thread — must not call signal.signal."""
    import signal
    import threading

    sig_calls: list[tuple] = []

    def _tracking_signal(sig, handler):
        sig_calls.append((threading.current_thread().name, sig, handler))
        raise AssertionError("signal.signal must not be called off the main thread")

    monkeypatch.setattr(signal, "signal", _tracking_signal)
    monkeypatch.setattr("kite.models.retry.is_transient_provider_error", lambda _e: False)

    agent = DefaultAgent(
        _BoomModel(),
        _StubEnv(),
        interactive=False,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    box: dict[str, object] = {}

    def worker() -> None:
        try:
            box["result"] = agent.run("do something")
        except Exception as e:  # noqa: BLE001 — capture for assertion
            box["error"] = e

    t = threading.Thread(target=worker, name="kite-turn-test")
    t.start()
    t.join(timeout=15)
    assert not t.is_alive()
    assert "error" not in box, box.get("error")
    result = box["result"]
    assert isinstance(result, dict)
    assert result.get("exit_status") == "Error"
    assert sig_calls == []


class _FailEnv:
    def execute(self, action: dict, cwd: str = "") -> dict:
        return {"ok": False, "output": "boom", "error": "boom", "returncode": 1}


def test_consecutive_tool_failures_nudge_not_to_claim_done() -> None:
    model = _TextOnlyModel("x")
    agent = DefaultAgent(
        model,
        _FailEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    turn = {
        "role": "assistant",
        "content": "",
        "extra": {"actions": [{"tool": "bash", "id": "1", "arguments": {"command": "pytest -q"}}]},
    }
    for _ in range(3):
        agent.execute_actions(turn)
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Do not claim the task is done" in blob
    assert agent._tool_fail_streak == 3


def test_inspection_bash_failure_does_not_count_as_tool_streak() -> None:
    model = _TextOnlyModel("x")
    agent = DefaultAgent(
        model,
        _FailEnv(),
        interactive=True,
        mode=AgentMode.BUILD,
        provider_max_retries=1,
    )
    turn = {
        "role": "assistant",
        "content": "",
        "extra": {
            "actions": [{"tool": "bash", "id": "1", "arguments": {"command": "rg foo src"}}]
        },
    }
    for _ in range(3):
        agent.execute_actions(turn)
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Do not claim the task is done" not in blob
    assert agent._tool_fail_streak == 0
