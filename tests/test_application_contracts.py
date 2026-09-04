"""Application contract and compatibility tests (Milestone A)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.agent.events import Event
from kite.agent.harness import Harness, HarnessConfig
from kite.application.adapters.harness import harness_config_from_run_spec, run_spec_from_harness_config
from kite.application.contracts import ModelSelection, RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.events import (
    EventSequencer,
    InMemoryEventSink,
    envelope_from_legacy,
    legacy_from_envelope,
)
from kite.application.service import ApplicationRunService
from kite.application.state import RunState, can_transition


def test_harness_config_roundtrip(workspace: Path) -> None:
    original = HarnessConfig(
        provider="groq",
        model_name="llama-3.3-70b-versatile",
        cwd=str(workspace),
        step_limit=10,
        cost_limit=1.5,
        mode="build",
        approval="manual",
        execution_mode="restricted",
    )
    spec = run_spec_from_harness_config(original, task="fix tests", workspace=workspace)
    assert spec.task == "fix tests"
    assert spec.workspace == workspace
    assert spec.model_selection.provider == "groq"
    assert spec.limits.step_limit == 10
    assert spec.approval_mode == "manual"
    assert spec.execution_mode == "restricted"

    restored = harness_config_from_run_spec(spec)
    assert restored.provider == original.provider
    assert restored.model_name == original.model_name
    assert restored.step_limit == original.step_limit
    assert restored.approval == original.approval
    assert restored.execution_mode == original.execution_mode


def test_harness_to_run_spec_helper(workspace: Path) -> None:
    h = Harness(config=HarnessConfig(cwd=str(workspace), provider="openai"))
    spec = h.to_run_spec("hello")
    assert spec.task == "hello"
    assert spec.model_selection.provider == "openai"


def test_run_state_transitions() -> None:
    state = RunState("created")
    state.transition("prepared")
    state.transition("awaiting_model")
    state.transition("completed")
    assert state.terminal
    assert not can_transition("completed", "awaiting_model")


def test_run_state_rejects_invalid_transition() -> None:
    state = RunState("created")
    with pytest.raises(ValueError, match="invalid run transition"):
        state.transition("completed")


def test_event_envelope_sequencing() -> None:
    seq = EventSequencer("run-1")
    e1 = seq.emit("turn_start", {"n": 1})
    e2 = seq.emit("turn_end", {"n": 1})
    assert e1.sequence == 1
    assert e2.sequence == 2
    assert e1.run_id == "run-1"
    assert e1.schema_version == 1


def test_legacy_event_bridge_roundtrip() -> None:
    seq = EventSequencer("run-2")
    legacy = Event(kind="tool_start", payload={"tool": "read"})
    envelope = envelope_from_legacy(legacy, run_id="run-2", sequencer=seq)
    back = legacy_from_envelope(envelope)
    assert back.kind == "tool_start"
    assert back.payload["tool"] == "read"


class _FakeHarness:
    """Minimal harness double for ApplicationRunService."""

    def __init__(self, result: dict) -> None:
        self.config = HarnessConfig()
        self._result = result
        self._listeners: list = []

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def run(self, task: str, *, cancel=None) -> dict:
        for listener in self._listeners:
            listener(Event(kind="agent_start", payload={"task": task}))
            listener(Event(kind="agent_end", payload=self._result))
        return self._result


def test_application_run_service_emits_envelopes() -> None:
    sink = InMemoryEventSink()
    deps = HarnessDependencies(event_sink=sink)
    service = ApplicationRunService()
    spec = RunSpec(
        task="demo",
        workspace=Path("."),
        run_id="run-test",
        model_selection=ModelSelection(provider="fake"),
    )
    fake = _FakeHarness({"exit_status": "Submitted", "submission": "done", "cost": 0.1})
    result = service.run(spec, deps=deps, harness=fake)  # type: ignore[arg-type]

    assert result.status == "completed"
    assert result.stop_reason == "submitted"
    assert result.final_message == "done"
    assert result.cost == 0.1

    events = sink.load_run("run-test")
    assert len(events) == 2
    assert events[0].kind == "agent_start"
    assert events[1].kind == "agent_end"
    assert events[0].sequence < events[1].sequence


def test_application_run_service_maps_error_status() -> None:
    service = ApplicationRunService()
    spec = RunSpec(task="x", workspace=Path("."))
    fake = _FakeHarness({"exit_status": "Error", "error": "boom"})
    result = service.run(spec, harness=fake)  # type: ignore[arg-type]
    assert result.status == "failed"
    assert result.stop_reason == "error"
