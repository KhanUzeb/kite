"""Headless task files and structured stderr display."""

from __future__ import annotations

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.tasks import (
    HeadlessRunDisplay,
    HeadlessTask,
    is_headless_run,
    load_tasks_text,
    parse_task_line,
    resolve_headless_approval,
    run_headless_batch,
    run_headless_task,
)


def test_task_parsing_plain_and_json_combined() -> None:
    # (merged from test_parse_plain_task_line)
    task = parse_task_line("fix the tests", default_cwd="/tmp/ws")
    assert task is not None
    assert task.task == "fix the tests"
    assert task.cwd == "/tmp/ws"
    # (merged from test_parse_json_task_line)
    row = '{"task": "scout auth", "label": "auth", "profile": "scout", "mode": "plan"}'
    json_task = parse_task_line(row)
    assert json_task is not None
    assert json_task.label == "auth"
    assert json_task.mode == "plan"


def test_task_loading_and_invalid_line_combined() -> None:
    # (merged from test_load_tasks_skips_comments_and_blanks)
    text = "# header\n\nrun tests\n\n{\"task\": \"lint\", \"label\": \"lint\"}\n"
    tasks = load_tasks_text(text, default_cwd=".")
    assert len(tasks) == 2
    assert tasks[0].task == "run tests"
    assert tasks[1].label == "lint"
    # (merged from test_invalid_json_task_line_raises)
    import pytest

    with pytest.raises(ValueError, match="invalid JSON"):
        parse_task_line("{not json}")


def test_headless_approval_resolution_combined() -> None:
    # (merged from test_resolve_headless_approval_preserves_user_mode)
    assert resolve_headless_approval("approve", AgentMode.BUILD, headless=True) is ApprovalMode.APPROVE
    assert resolve_headless_approval("readonly", AgentMode.BUILD, headless=True) is ApprovalMode.READONLY
    # (merged from test_resolve_headless_approval_uses_one_shot_auto_default)
    assert resolve_headless_approval(None, AgentMode.BUILD, headless=True) is ApprovalMode.AUTO


def test_headless_flags_and_cli_parsers_combined() -> None:
    # (merged from test_is_headless_run_flag)
    assert is_headless_run(headless_flag=True, quiet=False)
    assert is_headless_run(headless_flag=False, quiet=True)
    # (merged from test_kite_tasks_parser_registered)
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["tasks", "run", "tasks.jsonl", "--dry-run"])
    assert args.command == "tasks"
    assert args.tasks_action == "run"
    assert args.file == "tasks.jsonl"
    assert args.dry_run is True
    # (merged from test_kite_run_headless_flag)
    run_args = build_parser().parse_args(["run", "--headless", "--no-stream", "fix tests"])
    assert run_args.headless is True
    assert run_args.no_stream is True
    assert run_args.task == "fix tests"


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
