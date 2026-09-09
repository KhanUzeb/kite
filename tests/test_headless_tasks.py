"""Headless task files and structured stderr display."""

from __future__ import annotations

import pytest

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.tasks.headless import (
    HeadlessRunDisplay,
    HeadlessTask,
    is_headless_run,
    load_tasks_text,
    parse_task_line,
    resolve_headless_approval,
    run_headless_batch,
    run_headless_task,
)


def test_parse_plain_task_line() -> None:
    task = parse_task_line("fix the tests", default_cwd="/tmp/ws")
    assert task is not None
    assert task.task == "fix the tests"
    assert task.cwd == "/tmp/ws"


def test_parse_json_task_line() -> None:
    row = '{"task": "scout auth", "label": "auth", "profile": "scout", "mode": "plan"}'
    task = parse_task_line(row)
    assert task is not None
    assert task.label == "auth"
    assert task.mode == "plan"


def test_load_tasks_skips_comments_and_blanks() -> None:
    text = "# header\n\nrun tests\n\n{\"task\": \"lint\", \"label\": \"lint\"}\n"
    tasks = load_tasks_text(text, default_cwd=".")
    assert len(tasks) == 2
    assert tasks[0].task == "run tests"
    assert tasks[1].label == "lint"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("approve", ApprovalMode.APPROVE), ("readonly", ApprovalMode.READONLY)],
)
def test_resolve_headless_approval_preserves_user_mode(raw: str, expected: ApprovalMode) -> None:
    assert resolve_headless_approval(raw, AgentMode.BUILD, headless=True) is expected


def test_is_headless_run_flag() -> None:
    assert is_headless_run(headless_flag=True, quiet=False)
    assert is_headless_run(headless_flag=False, quiet=True)


def test_headless_display_tool_start(capsys) -> None:
    display = HeadlessRunDisplay(stream_tools=True)
    display(Event("tool_start", payload={"tool": "bash", "arguments": {"command": "pytest -q"}}))
    err = capsys.readouterr().err
    assert "[tool]" in err
    assert "pytest" in err


def test_headless_display_subagent(capsys) -> None:
    display = HeadlessRunDisplay()
    display(
        Event(
            "subagent_start",
            payload={"label": "scout", "profile": "scout", "id": "abc"},
        )
    )
    err = capsys.readouterr().err
    assert "[crew]" in err
    assert "scout" in err


def test_run_headless_batch_dry_integration(monkeypatch, workspace, kite_home) -> None:
    calls: list[str] = []

    def fake_run(task: HeadlessTask, **kwargs):  # noqa: ANN003
        calls.append(task.task)
        from kite.tasks.headless import HeadlessTaskResult

        return HeadlessTaskResult(
            index=0,
            label=task.label,
            ok=True,
            exit_status="Submitted",
            session_id="s1",
        )

    monkeypatch.setattr("kite.tasks.headless.run_headless_task", fake_run)
    tasks = [
        HeadlessTask(task="one", label="a"),
        HeadlessTask(task="two", label="b"),
    ]
    batch = run_headless_batch(tasks, continue_on_error=True)
    assert batch.ok
    assert calls == ["one", "two"]


@pytest.mark.parametrize(
    ("approval", "expected"),
    [("auto", "allow"), ("readonly", "deny"), ("approve", "deny")],
)
def test_headless_task_wires_noninteractive_approval(
    monkeypatch, workspace, kite_home, approval: str, expected: str
) -> None:
    from kite.application.contracts import RunResult

    observed: list[str] = []

    def fake_execute(harness, task):  # noqa: ANN001, ANN202
        observed.append(
            harness.approver("write", {"path": str(workspace / "generated.txt")}, {})
        )
        return RunResult(
            status="completed",
            stop_reason="submitted",
            final_message="done",
            legacy={"exit_status": "Submitted", "submission": "done"},
        )

    monkeypatch.setattr("kite.application.cli.runner.execute_harness_task", fake_execute)
    result = run_headless_task(
        HeadlessTask(task="generate a file", cwd=str(workspace), approval=approval)
    )

    assert result.ok is True
    assert observed == [expected]


def test_invalid_json_task_line_raises() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_task_line("{not json}")


def test_kite_tasks_parser_registered() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["tasks", "run", "tasks.jsonl", "--dry-run"])
    assert args.command == "tasks"
    assert args.tasks_action == "run"
    assert args.file == "tasks.jsonl"
    assert args.dry_run is True


def test_kite_run_headless_flag() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["run", "--headless", "--no-stream", "fix tests"])
    assert args.headless is True
    assert args.no_stream is True
    assert args.task == "fix tests"
