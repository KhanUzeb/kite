"""Headless task files and structured stderr display."""

from __future__ import annotations

from kite.agent.events import Event
from kite.tasks import (
    HeadlessRunDisplay,
    HeadlessTask,
    run_headless_batch,
    run_headless_task,
)


def test_headless_display_combined(capsys) -> None:
    # (merged from test_headless_display_tool_start)
    display = HeadlessRunDisplay(stream_tools=True)
    display(Event("tool_start", payload={"tool": "bash", "arguments": {"command": "pytest -q"}}))
    err = capsys.readouterr().err
    assert "[tool]" in err
    assert "pytest" in err
    # (merged from test_headless_display_subagent)
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


def test_headless_batch_and_approval_wiring_combined(monkeypatch, workspace, kite_home) -> None:
    # (merged from test_run_headless_batch_dry_integration)
    calls: list[str] = []

    def fake_run(task: HeadlessTask, **kwargs):  # noqa: ANN003
        calls.append(task.task)
        from kite.tasks import HeadlessTaskResult

        return HeadlessTaskResult(
            index=0,
            label=task.label,
            ok=True,
            exit_status="Submitted",
            session_id="s1",
        )

    monkeypatch.setattr("kite.tasks.run_headless_task", fake_run)
    tasks = [
        HeadlessTask(task="one", label="a"),
        HeadlessTask(task="two", label="b"),
    ]
    batch = run_headless_batch(tasks, continue_on_error=True)
    assert batch.ok
    assert calls == ["one", "two"]
    # (merged from test_headless_task_wires_noninteractive_approval)
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


def test_headless_budgets_leftover_jobs_and_cli_flags(monkeypatch, workspace, kite_home) -> None:
    from unittest.mock import MagicMock

    from kite.application.contracts import RunResult
    from kite.cli.run import build_parser, cmd_exec
    from kite.cli.tasks import cmd_tasks

    seen: dict = {}

    def fake_build(**kwargs):  # noqa: ANN003
        seen.update(kwargs)
        return MagicMock()

    class FakeHarness:
        def __init__(self, config) -> None:  # noqa: ANN001
            self.config = config
            self.last_session = None
            self.approver = None

        def subscribe(self, *_a, **_k) -> None:
            return None

        def teardown_jobs(self) -> int:
            return 2

    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", fake_build)
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
    leftover = run_headless_task(
        HeadlessTask(task="do work", cwd=str(workspace)),
        step_limit=7,
        cost_limit=1.25,
        wall_time_limit_seconds=30,
    )
    assert leftover.ok is False
    assert "leftover" in leftover.error
    assert seen["step_limit"] == 7 and seen["cost_limit"] == 1.25

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

    parser = build_parser()
    budgeted = parser.parse_args(["tasks", "run", "batch.jsonl", "--steps", "9", "--cost", "2.5", "--time", "15"])
    assert budgeted.steps == 9 and budgeted.cost == 2.5 and budgeted.time == 15
    missing = parser.parse_args(["tasks", "run"])
    assert cmd_tasks(missing) == 2
    captured: dict = {}

    def fake_cmd_run(args) -> int:  # noqa: ANN001
        captured.update(headless=args.headless, quiet=args.quiet, steps=args.steps)
        return 0

    monkeypatch.setattr("kite.cli.run.cmd_run", fake_cmd_run)
    exec_args = parser.parse_args(["exec", "--steps", "4", "ci task"])
    assert cmd_exec(exec_args) == 0
    assert captured["headless"] is True and captured["quiet"] is True and captured["steps"] == 4
