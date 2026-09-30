"""Loop continuation: stall maps to recoverable fault, stops auto-resume with work."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import ProviderFault
from kite.agent.loop import DefaultAgent, _is_stream_stall
from kite.env.local import LocalEnvironment
from kite.memory.continuity import has_unfinished_work
from kite.memory.recovery import (
    decide_recovery_continue,
    recoverable_stop_hint,
    should_auto_recover,
)
from kite.tools import ToolRegistry


class _StallModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def query(self, messages):
        from kite.models.litellm_model import StreamStalledError

        raise StreamStalledError("stream stalled: no data for 30s")

    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": str(outputs)}]


class _FailOnceEnv:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, action: dict, cwd: str = "") -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"ok": False, "error": "boom", "output": "boom"}
        return {"ok": True, "output": "ok"}


def _agent(model, env=None, **kw):
    env = env or LocalEnvironment(registry=ToolRegistry([]))
    return DefaultAgent(model, env, provider_max_retries=2, **kw)


def test_stream_stall_maps_to_provider_fault_not_error() -> None:
    assert _is_stream_stall(TimeoutError("stream timed out after 5s without completing"))
    from kite.models.litellm_model import StreamStalledError

    assert _is_stream_stall(StreamStalledError("stream stalled: no data for 30s"))
    assert not _is_stream_stall(RuntimeError("provider exploded"))

    agent = _agent(_StallModel())
    agent.messages = [{"role": "user", "content": "hi"}]
    with pytest.raises(ProviderFault) as ei:
        agent.query()
    assert "stalled" in ei.value.error.lower()


def test_cancel_beats_stall() -> None:
    agent = _agent(_StallModel())
    agent.messages = [{"role": "user", "content": "hi"}]
    agent._interrupt = True
    from kite.agent.exceptions import Interrupted

    with pytest.raises(Interrupted):
        agent.query()


def test_stalled_error_auto_continue_with_work() -> None:
    todos = [{"status": "pending", "content": "finish edit"}]
    assert has_unfinished_work(todos=todos, exit_status="Stalled", tool_call_count=0)
    assert has_unfinished_work(todos=[], exit_status="Stalled", tool_call_count=2)
    assert not has_unfinished_work(todos=[], exit_status="Stalled", tool_call_count=0)
    assert not has_unfinished_work(todos=[], exit_status="Submitted", tool_call_count=5)

    assert should_auto_recover(exit_status="Stalled", continues_used=0, tool_call_count=2)
    assert should_auto_recover(
        exit_status="Error", continues_used=0, todos=todos, tool_call_count=0
    )
    assert should_auto_recover(
        exit_status="RepeatedFormatError", continues_used=0, tool_call_count=1
    )
    assert not should_auto_recover(exit_status="Stalled", continues_used=0, tool_call_count=0)
    assert not should_auto_recover(
        exit_status="Stalled", continues_used=0, tool_call_count=2, inbox_queued=True
    )
    assert (
        decide_recovery_continue(exit_status="Error", continues_used=0, tool_call_count=3)
        == "continue"
    )


def test_tool_failure_does_not_end_loop() -> None:
    class _ToolModel:
        def format_message(self, **kwargs):
            return dict(kwargs)

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [
                {"role": "tool", "tool_call_id": "c1", "content": str(o.get("output"))}
                for o in outputs
            ]

    agent = _agent(_ToolModel(), _FailOnceEnv())
    msg = {
        "role": "assistant",
        "content": "",
        "extra": {"actions": [{"tool": "bash", "id": "c1", "arguments": {"command": "false"}}]},
    }
    obs = agent.execute_actions(msg)
    assert obs and agent.tool_call_count >= 0
    # No exit marker — the loop continues after a single tool failure.
    assert not agent.messages or agent.messages[-1].get("role") != "exit"


def test_recoverable_stop_hint_suggests_continue() -> None:
    hint = recoverable_stop_hint("Stalled", "Stopped after 3 idle turns")
    assert hint is not None and "continue" in hint and "Stopped after 3 idle turns" in hint
    assert recoverable_stop_hint("Submitted", "done") is None
