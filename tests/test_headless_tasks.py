"""Headless task files and structured stderr display."""

from __future__ import annotations

from kite.agent.events import Event
from kite.tasks import (
    HeadlessRunDisplay,
    HeadlessTask,
    run_headless_task,
)


def test_headless_display_tool_and_subagent_events(capsys) -> None:
    display = HeadlessRunDisplay(stream_tools=True)
    display(Event("tool_start", payload={"tool": "bash", "arguments": {"command": "pytest -q"}}))
    err = capsys.readouterr().err
    assert "[tool]" in err
    assert "pytest" in err
    crew_display = HeadlessRunDisplay()
    crew_display(
        Event(
            "subagent_start",
            payload={"label": "scout", "profile": "scout", "id": "abc"},
        )
    )
    crew_err = capsys.readouterr().err
    assert "[crew]" in crew_err
    assert "scout" in crew_err


def test_headless_noninteractive_approval_modes(monkeypatch, workspace, kite_home) -> None:
    from kite.application.contracts import RunResult

    for approval, expected in (("auto", "allow"), ("readonly", "deny"), ("approve", "deny")):
        observed: list[str] = []

        def fake_execute(harness, task, _observed=observed):  # noqa: ANN001, ANN202
            _observed.append(
                harness.approver("write", {"path": str(workspace / "generated.txt")}, {})
            )
            return RunResult(
                status="completed",
                stop_reason="submitted",
                final_message="done",
                legacy={"exit_status": "Submitted", "submission": "done"},
            )

        monkeypatch.setattr("kite.application.cli.execute_harness_task", fake_execute)
        result = run_headless_task(
            HeadlessTask(task="generate a file", cwd=str(workspace), approval=approval)
        )
        assert result.ok is True
        assert observed == [expected]


def test_headless_leftover_jobs_and_exceeded_limits_fail(monkeypatch, workspace, kite_home) -> None:
    from unittest.mock import MagicMock

    from kite.application.contracts import RunResult

    class FakeHarness:
        def __init__(self, config) -> None:  # noqa: ANN001
            self.config = config
            self.last_session = None
            self.approver = None

        def subscribe(self, *_a, **_k) -> None:
            return None

        def teardown_jobs(self) -> int:
            return 2

    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", lambda **_kwargs: MagicMock())
    monkeypatch.setattr("kite.agent.harness.Harness", FakeHarness)
    monkeypatch.setattr(
        "kite.application.cli.execute_harness_task",
        lambda *_a, **_k: RunResult(
            status="completed",
            stop_reason="submitted",
            final_message="done",
            legacy={"exit_status": "Submitted", "submission": "done"},
        ),
    )
    leftover = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert leftover.ok is False
    assert "leftover" in leftover.error

    monkeypatch.setattr(
        "kite.application.cli.execute_harness_task",
        lambda *_a, **_k: RunResult(
            status="failed",
            stop_reason="limits_exceeded",
            final_message="",
            legacy={"exit_status": "LimitsExceeded"},
        ),
    )

    class CleanHarness(FakeHarness):
        def teardown_jobs(self) -> int:
            return 0

    monkeypatch.setattr("kite.agent.harness.Harness", CleanHarness)
    limited = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert limited.ok is False and limited.exit_status == "LimitsExceeded"


def test_tasks_command_requires_file() -> None:
    from kite.cli.run import build_parser
    from kite.cli.tasks import cmd_tasks

    parser = build_parser()
    missing = parser.parse_args(["tasks", "run"])
    assert cmd_tasks(missing) == 2


def test_headless_jsonl_trace_redacts_bounds_and_appends(monkeypatch, workspace, kite_home, tmp_path, capsys) -> None:
    import json
    import stat
    import sys
    import time
    from types import SimpleNamespace

    from kite.agent.harness import Harness
    from kite.agent.runtime import AgentRuntime
    from kite.config import AgentRuntimeConfig

    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("KITE_TRACE_JSONL", str(trace_path))
    secret = "trace-fake-secret-do-not-persist"
    (workspace / "sample.txt").write_text(f"Authorization: Bearer {secret}\n" + "x" * 8000, encoding="utf-8")
    resolved = SimpleNamespace(provider="stub", model="stub", context_window=100_000)
    config = AgentRuntimeConfig(auto_compact=False, auto_venv=False, context7_enabled=False)
    config.tools.enabled = ["read", "submit"]
    monkeypatch.setattr(AgentRuntime, "prepare", lambda self: (config, resolved, "Test system prompt"))
    seen = []
    runtimes = []

    class StubModel:
        def __init__(self, *, on_event, **kwargs):
            self.on_event = on_event
            self.resolved = resolved
            self.calls = 0

        def format_message(self, **kwargs):
            return dict(kwargs)

        def query(self, messages):
            self.calls += 1
            self.on_event(Event("stream_start", {"model": "stub"}))
            self.on_event(Event("stream_delta", {"text": "working " * 1000, "headers": {"authorization": secret}}))
            self.on_event(Event("stream_end", {}))
            action = (
                {"tool": "read", "arguments": {"path": "sample.txt"}}
                if self.calls == 1 else {"tool": "submit", "arguments": {"message": "Inspected sample.txt."}}
            )
            return {"role": "assistant", "content": "", "extra": {"actions": [action], "cost": 0.0}}

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [{"role": "tool", "content": json.dumps(output)} for output in outputs]

    def make_harness(config):
        config.no_extensions = True
        harness = Harness(config).use("model", StubModel)
        harness.subscribe(seen.append)
        runtimes.append(harness._runtime)
        return harness

    monkeypatch.setattr("kite.agent.harness.Harness", make_harness)
    task = HeadlessTask(task="Inspect sample.txt and report its contents.", cwd=str(workspace))
    started = time.time()
    result = run_headless_task(task, no_context=True, no_compact=True, step_limit=3)
    assert result.ok, result.error
    text = trace_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert [row["type"] for row in rows] == [event.kind for event in seen]
    kinds = [row["type"] for row in rows]
    assert kinds[0] == "agent_start" and kinds[-1] == "agent_end"
    assert kinds.index("agent_start") < kinds.index("stream_start") < kinds.index("tool_start") < kinds.index("tool_end")
    assert rows[-1]["exit_status"] == "Submitted"
    assert len({row["run_id"] for row in rows}) == 1 and rows[0]["run_id"]
    assert all(started <= row["ts"] <= time.time() for row in rows)
    assert 0 <= rows[0]["t"] <= rows[-1]["t"]
    assert [row["t"] for row in rows] == sorted(row["t"] for row in rows)
    assert secret not in text
    output = next(row["output"] for row in rows if row["type"] == "tool_end" and row["tool"] == "read")
    assert "[REDACTED]" in output and output.endswith("…[truncated]") and len(output) <= 4096
    delta = next(row for row in rows if row["type"] == "stream_delta")
    assert len(delta["text"]) <= 4096 and delta["text"].endswith("…[truncated]")
    assert delta["headers"]["authorization"] == "[REDACTED]"
    original = next(event for event in seen if event.kind == "stream_delta")
    assert original.payload["headers"]["authorization"] == secret and len(original.payload["text"]) == 8000
    if sys.platform != "win32":
        assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600

    # Reusing a runtime (REPL turns) appends a fresh run ID without retaining a sink.
    seen.clear()
    monkeypatch.delenv("KITE_TRACE_JSONL")
    second = runtimes[0].run(task.task)
    assert second["exit_status"] == "Submitted"
    appended = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert appended[:len(rows)] == rows
    assert len({row["run_id"] for row in appended}) == 2
    assert [row["type"] for row in appended[len(rows):]] == [event.kind for event in seen]

    # An unavailable trace destination must not change a headless run's outcome.
    capsys.readouterr()
    monkeypatch.setenv("KITE_TRACE_JSONL", str(tmp_path))
    assert run_headless_task(task, no_context=True, no_compact=True, step_limit=3).ok
    assert capsys.readouterr().err.count("KITE_TRACE_JSONL failed") == 1


def test_jsonl_trace_windows_permissions_are_best_effort(monkeypatch, tmp_path, capsys) -> None:
    import json
    import os
    from types import SimpleNamespace

    from kite.agent import runtime

    # Model Windows without changing the host platform or pathlib's behavior.
    trace_os = SimpleNamespace(**vars(os))
    trace_os.name = "nt"
    monkeypatch.delattr(trace_os, "fchmod", raising=False)

    def denied_chmod(path, mode):
        raise PermissionError("Windows permissions cannot be tightened")

    trace_os.chmod = denied_chmod
    monkeypatch.setattr(runtime, "os", trace_os)
    trace_path = tmp_path / "trace.jsonl"
    trace = runtime._JsonlTrace(str(trace_path))
    try:
        trace(Event("agent_start", {"task": "trace on Windows"}))
    finally:
        trace.close()
    row = json.loads(trace_path.read_text(encoding="utf-8"))
    assert row["type"] == "agent_start" and row["task"] == "trace on Windows"
    assert "KITE_TRACE_JSONL failed" not in capsys.readouterr().err
