"""Application contracts, policy/executor, verification, nested policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.agent.events import Event
from kite.agent.exceptions import Submitted
from kite.agent.harness import Harness, HarnessConfig
from kite.agent.verification import VerificationCollector
from kite.application.adapters import harness_config_from_run_spec, run_spec_from_harness_config
from kite.application.contracts import ModelSelection, RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.events import EventSequencer, InMemoryEventSink, envelope_from_legacy, legacy_from_envelope
from kite.application.execution import ChangeJournal, ProcessRunner, ToolExecutor
from kite.application.policy import ApprovalCoordinator, PolicyEngine, check_path_access, child_inherits_parent_policy
from kite.application.service import ApplicationRunService
from kite.application.state import RunState, can_transition
from kite.application.tools import ToolCall, derive_effects, normalize_legacy_effect
from kite.application.verification import (
    CheckSpec,
    VerificationRecord,
    build_verification_plan,
    classify_path,
    html_parse_ok,
    next_required_check_command,
    plan_status,
    record_satisfies_check,
)
from kite.eval import ReplayBundle, run_replay


def test_flattened_modules_export_public_names() -> None:
    from kite import tasks
    from kite.application import adapters, cli, execution, model, persistence, policy, tools, verification
    from kite.plugins import extensions

    assert execution.ToolExecutor and execution.build_tool_executor and execution.ProcessRunner
    assert policy.PolicyEngine and policy.ApprovalCoordinator
    assert tools.ToolCall and tools.derive_effects
    assert verification.EvidenceVerifier and verification.build_verification_plan
    assert cli.execute_harness_task and adapters.run_spec_from_harness_config
    assert model.ModelGateway and persistence.SQLiteEventStore
    assert ReplayBundle is not None and tasks.run_headless_task
    assert extensions.load_extensions


class _FakeHarness:
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


def test_run_spec_roundtrip_and_service(workspace: Path) -> None:
    original = HarnessConfig(
        provider="groq",
        model_name="llama-3.3-70b-versatile",
        cwd=str(workspace),
        step_limit=10,
        cost_limit=1.5,
        mode="build",
        approval="manual",
        execution_mode="restricted",
        memory_in_prompt=True,
    )
    spec = run_spec_from_harness_config(original, task="fix tests", workspace=workspace)
    restored = harness_config_from_run_spec(spec)
    assert restored.provider == original.provider and restored.memory_in_prompt is True
    wired = Harness(config=HarnessConfig(cwd=str(workspace), memory_in_prompt=True, role="debugger"))
    assert wired.to_run_spec("keep memory flag").memory_in_prompt is True
    sink = InMemoryEventSink()
    service = ApplicationRunService()
    fake = _FakeHarness({"exit_status": "Submitted", "submission": "done", "cost": 0.1})
    result = service.run(RunSpec(task="demo", workspace=Path("."), run_id="run-test", model_selection=ModelSelection(provider="fake")), deps=HarnessDependencies(event_sink=sink), harness=fake)  # type: ignore[arg-type]
    assert result.status == "completed" and result.stop_reason == "submitted"
    events = sink.load_run("run-test")
    assert [e.kind for e in events] == ["agent_start", "agent_end"]
    failed = service.run(RunSpec(task="x", workspace=Path(".")), harness=_FakeHarness({"exit_status": "Error", "error": "boom"}))  # type: ignore[arg-type]
    assert failed.status == "failed"


def test_run_state_and_legacy_event_bridge() -> None:
    state = RunState("created")
    state.transition("prepared")
    state.transition("awaiting_model")
    state.transition("completed")
    assert state.terminal and not can_transition("completed", "awaiting_model")
    with pytest.raises(ValueError, match="invalid run transition"):
        RunState("created").transition("completed")
    seq = EventSequencer("run-1")
    e1 = seq.emit("turn_start", {"n": 1})
    e2 = seq.emit("turn_end", {"n": 1})
    assert e1.sequence == 1 and e2.sequence == 2
    legacy = Event(kind="tool_start", payload={"tool": "read"})
    back = legacy_from_envelope(envelope_from_legacy(legacy, run_id="run-2", sequencer=EventSequencer("run-2")))
    assert back.kind == "tool_start" and back.payload["tool"] == "read"


def test_policy_paths_executor_and_journal(workspace: Path, tmp_path: Path) -> None:
    ok, _ = check_path_access("../outside", workspace)
    assert not ok
    sibling = tmp_path / "proj-ok"
    evil = tmp_path / "proj-evil"
    sibling.mkdir()
    evil.mkdir()
    (evil / "secret.txt").write_text("no\n", encoding="utf-8")
    blocked, reason = check_path_access(evil / "secret.txt", sibling)
    assert not blocked
    other = tmp_path / "other"
    other.mkdir()
    target = other / "file.txt"
    target.write_text("ok\n", encoding="utf-8")
    allowed, _ = check_path_access(target, sibling, execution_mode="host")
    denied, _ = check_path_access(target, sibling, execution_mode="restricted")
    assert allowed and not denied
    engine = PolicyEngine(workspace)
    curl = ToolCall(call_id="1", name="bash", arguments={"command": "curl http://evil.com"})
    assert not engine.authorize(engine.derive_intent(curl)).allowed
    restricted = PolicyEngine(workspace, execution_mode="restricted")
    assert not restricted.authorize(restricted.derive_intent(curl)).allowed
    executor = ToolExecutor(policy=engine, runner=lambda c: {"ok": True, "output": "done"}, approver=lambda i, d: False)
    write = ToolCall(call_id="w1", name="write", arguments={"path": "src/app.py", "content": "x"})
    assert executor.execute(write).status == "denied"
    assert executor.execute(write, skip_approval=True).ok
    def _raise(_call):
        raise Submitted({"role": "exit", "content": "done", "extra": {"exit_status": "Submitted"}})

    with pytest.raises(Submitted):
        ToolExecutor(policy=engine, runner=_raise).execute(ToolCall(call_id="s1", name="read", arguments={"path": "src/app.py"}), skip_approval=True)
    failed = ToolExecutor(policy=engine, runner=lambda c: {"ok": False, "returncode": 2, "output": "fail", "error": "fail"}).execute(
        ToolCall(call_id="b1", name="bash", arguments={"command": "pytest -q"}), skip_approval=True
    )
    assert failed.metadata.get("returncode") == 2
    app = workspace / "src" / "app.py"
    original = app.read_text(encoding="utf-8")
    journal = ChangeJournal(workspace)
    journal.record_write(app)
    app.write_text("agent only\n", encoding="utf-8")
    journal.record_after_write(app)
    restored, conflicts = journal.restore()
    assert not conflicts and app.read_text(encoding="utf-8") == original
    journal.record_write(app)
    app.write_text("agent edit\n", encoding="utf-8")
    journal.record_after_write(app)
    app.write_text("user edit\n", encoding="utf-8")
    _, conflicts = journal.restore()
    assert conflicts and app.read_text(encoding="utf-8") == "user edit\n"


def test_verification_plans_and_replay(workspace: Path, tmp_path: Path) -> None:
    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "pytest tests/ -q"}, {"ok": True, "returncode": 0, "output": "out"})
    assert any(a.kind == "test" for a in vc.artifacts) and vc.status() == "verified"
    idle = VerificationCollector()
    idle.on_tool_end("edit", {"path": "x.py"}, {"ok": True, "path": "x.py", "diff": "d"})
    assert idle.needs_tests()
    html = "<html><body>ok</body></html>"
    html_vc = VerificationCollector()
    html_vc.on_tool_end("write", {"path": "index.html", "content": html}, {"ok": True, "path": "index.html", "diff": "d", "content": html})
    assert not html_vc.needs_tests()
    assert html_parse_ok(html) and not html_parse_ok("<html><body>no closing tags")
    (workspace / "tests").mkdir(exist_ok=True)
    (workspace / "tests" / "test_app.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    python_vc = VerificationCollector(workspace_root=str(workspace))
    python_vc.on_tool_end("edit", {"path": "src/app.py"}, {"ok": True, "path": "src/app.py", "diff": "d"})
    cmd = next_required_check_command(python_vc)
    assert cmd and ("pytest" in cmd.lower() or "py_compile" in cmd.lower())
    evidence = VerificationCollector(workspace_root=str(tmp_path), run_id="run-ev")
    evidence.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "3 passed"})
    assert evidence.summary().get("evidence", {}).get("status") == "verified"
    html_plan = build_verification_plan(("dashboard.html",))
    assert html_plan.required_checks[0].artifact_kind == "html"
    assert all(c.command is None or "pytest" not in (c.command or "").lower() for c in html_plan.required_checks)
    assert classify_path("x.py") == "python"
    pytest_record = VerificationRecord(
        check=CheckSpec(kind="project_test", command="pytest -q", affected_paths=("a.py",), artifact_kind="python"),
        command="pytest -q",
        affected_paths=("a.py",),
        exit_status=0,
        ok=True,
        output_summary="1 passed",
    )
    assert not record_satisfies_check(pytest_record, html_plan.required_checks[0])
    assert plan_status(build_verification_plan(("README",)), []) == "changed_unverified"
    bundle = ReplayBundle(
        run_id="acc-1",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "Done — html updated."}],
        events=[{"kind": "verification_status", "payload": {"status": "verified"}}],
        acceptance={"content_contains": "html updated", "content_excludes": "pytest", "min_events": 1, "event_kinds": ["verification_status"]},
    )
    assert run_replay(bundle)["ok"]
    fail = ReplayBundle(
        run_id="acc-2", prompt_hash="h", context_snapshot_id="s", config_hash="c", model="fake", provider="fake",
        tool_catalog_hash="t", workspace_fingerprint="w", responses=[{"role": "assistant", "content": "nope"}],
        acceptance={"content_contains": "expected phrase"},
    )
    assert not run_replay(fail)["ok"]


def test_effects_nested_policy_and_coordinator(workspace: Path) -> None:
    assert set(derive_effects(ToolCall("1", "bash", {"command": "rm -rf build"}))) == {"destructive", "long_running"}
    assert derive_effects(ToolCall("1", "memory", {"action": "remember", "text": "x"})) == ("durable_memory",)
    assert normalize_legacy_effect("read") == "workspace_read"
    inherited = child_inherits_parent_policy(parent_approval="approve", parent_mode="build", parent_no_guardrails=False, parent_execution_mode="restricted", child_overrides={"approval": "yolo", "no_guardrails": True})
    assert inherited["approval"] == "approve" and inherited["no_guardrails"] is False
    locked = child_inherits_parent_policy(parent_approval="auto", parent_mode="plan", parent_no_guardrails=False, parent_execution_mode="restricted", child_overrides={"mode": "build", "execution_mode": "host"})
    assert locked["mode"] == "plan" and locked["execution_mode"] == "restricted"
    coord = ApprovalCoordinator(interactive=True, timeout_seconds=0.05)
    assert coord.request("bash", {"command": "curl x"}, mandatory=True) == "deny"
    assert coord.pending is None
    import sys

    runner = ProcessRunner(timeout_seconds=5.0)
    result = runner.run(["cmd", "/c", "echo", "hi"] if sys.platform == "win32" else ["echo", "hi"])
    assert result.exit_code == 0 and "hi" in result.stdout


def test_cli_result_ok_only_when_submitted() -> None:
    from kite.application.cli import CliResult
    from kite.application.contracts import RunResult
    from kite.application.service import _map_exit_status

    assert _map_exit_status("") == ("failed", "error")
    assert _map_exit_status(None) == ("failed", "error")
    assert _map_exit_status("LimitsExceeded") == ("failed", "limits_exceeded")
    submitted = RunResult(status="completed", stop_reason="submitted", final_message="ok")
    assert CliResult.from_run_result(submitted).ok is True
    unfinished = RunResult(status="completed", stop_reason="", final_message="still going")
    assert CliResult.from_run_result(unfinished).ok is False
    limited = RunResult(status="failed", stop_reason="limits_exceeded", final_message="steps")
    assert CliResult.from_run_result(limited).ok is False
