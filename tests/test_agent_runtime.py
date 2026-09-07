"""Pi-style runtime: steer continuation, follow-ups, compaction events."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.loop import DefaultAgent
from kite.agent.queue import RunMessageQueue
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry


class _StubModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def __init__(self) -> None:
        self.calls = 0

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [{"role": "tool", "content": str(outputs)}]

    def query(self, messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "working",
                "extra": {"actions": [{"tool": "read", "arguments": {"path": "x"}}], "cost": 0.0},
            }
        return {"role": "assistant", "content": "done after steer", "extra": {"cost": 0.0}}


def test_steer_continues_loop_instead_of_exiting() -> None:
    queue = RunMessageQueue()
    queue.steer("focus on tests only")
    events: list[str] = []
    model = _StubModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        step_limit=5,
        message_queue=queue,
        on_event=lambda e: events.append(e.kind),
    )
    agent.messages = [
        model.format_message("system", content="sys"),
        model.format_message("user", content="ship it"),
    ]

    def _interrupt_mid_tool(*_a, **_k):
        agent.request_interrupt()
        return {"ok": True, "output": "file"}

    agent.env.execute = _interrupt_mid_tool  # type: ignore[method-assign]

    result = agent.run("ship it")
    assert result.get("exit_status") != "Interrupted"
    user_texts = [str(m.get("content") or "") for m in agent.messages if m.get("role") == "user"]
    assert any("focus on tests only" in t for t in user_texts)
    assert "steer" in events


def test_follow_up_injected_at_turn_boundary() -> None:
    queue = RunMessageQueue()
    queue.enqueue("also add logging")
    events: list[str] = []

    class _TwoStepModel(_StubModel):
        def query(self, messages):
            self.calls += 1
            if self.calls == 1:
                return {"role": "assistant", "content": "ok", "extra": {"cost": 0.0}}
            return {"role": "assistant", "content": "logged", "extra": {"cost": 0.0}}

    model = _TwoStepModel()
    agent = DefaultAgent(
        model,
        LocalEnvironment(registry=ToolRegistry([])),
        step_limit=3,
        message_queue=queue,
        on_event=lambda e: events.append(e.kind),
    )
    agent.run("start")
    assert any("also add logging" in str(m.get("content") or "") for m in agent.messages if m.get("role") == "user")
    assert "follow_up" in events


def test_compaction_emits_start_and_end() -> None:
    kinds: list[str] = []
    compactor = LoopCompactor(
        CompactionConfig(enabled=True, window=1000, compact_ratio=0.5),
        system="sys",
        on_event=lambda e: kinds.append(e.kind),
    )
    messages = [
        {"role": "system", "content": "x" * 400},
        {"role": "user", "content": "y" * 400},
        {"role": "assistant", "content": "z" * 400},
    ]
    compactor.maybe_compact(messages, force=True)
    assert "compaction_start" in kinds
    assert "compaction_end" in kinds


def test_after_prepare_hook_fires(monkeypatch) -> None:
    from kite.agent.hooks import HookBus
    from kite.agent.runtime import AgentRuntime, RuntimeOptions

    fired: list[str] = []
    runtime = AgentRuntime(RuntimeOptions(cwd="."), hooks=HookBus())
    runtime.hooks.on("after_prepare", lambda **_: fired.append("yes"))
    monkeypatch.setattr(
        "kite.agent.runtime.resolve_model",
        lambda **_: MagicMock(provider="test", model="m", context_window=128000),
    )
    monkeypatch.setattr("kite.providers.resolve.missing_credentials", lambda _: None)
    monkeypatch.setattr("kite.providers.resolve.missing_model", lambda _: None)
    runtime.prepare()
    assert fired == ["yes"]
