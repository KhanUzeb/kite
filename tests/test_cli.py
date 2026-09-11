"""CLI apply, slash help, chat/resume flags, headless tasks."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.cli.apply_cmd import _path_inside_workspace, apply_unified_diff
from kite.cli.slash import CommandIndex, help_text
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
from kite.ui.commands import LEGACY_ALIASES, parse_slash
from kite.ui.pick import numbered_pick
from kite.ui.repl import ChatSession


def test_apply_diff_and_pickers(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root2"
    sibling.mkdir()
    assert not _path_inside_workspace(sibling, root)
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    result = apply_unified_diff("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-hello\n+world\n", cwd=str(tmp_path))
    assert result["count"] == 1 and target.read_text(encoding="utf-8") == "world\n"
    console = MagicMock()
    console.input.return_value = "2"
    assert numbered_pick(console, [("a", "alpha"), ("b", "beta")], current="a", title="t", noun="model") == "b"
    console.input.return_value = ""
    assert numbered_pick(console, [("a", "alpha")], current=None, title="t", noun="item") is None


def test_slash_help_and_legacy_routing() -> None:
    assert parse_slash("/select groq").command == "select"
    assert parse_slash("/thinking").command == "reasoning"
    assert parse_slash("/skill commit").command == "skill"
    assert parse_slash("/collapse").command == "collapse"
    assert "skill" not in LEGACY_ALIASES
    session = ChatSession.__new__(ChatSession)
    cmd, arg = session._apply_legacy_slash("model", "groq", "select")
    assert cmd == "model" and arg == "select groq"
    text = help_text(CommandIndex.load("."))
    assert "/plan" in text and "More: /help all" in text
    text_all = help_text(CommandIndex.load("."), all=True)
    assert "session" in text_all and "/select" in text_all
    from kite import __version__

    assert "kite_commands.md" in text_all and "CONTEXT.md" in text_all
    assert "architecture.md" in text_all and "SECURITY.md" in text_all
    assert f"docs/RELEASE-{__version__}.md" in text_all
    assert "kite-system-design" not in text and "docs/memory.md" not in text


def test_chat_flags_rejects_and_resume(monkeypatch, tmp_path: Path, kite_home) -> None:
    captured: dict = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self) -> int:
            return 0

    monkeypatch.setattr("kite.ui.repl.ChatSession", FakeSession)
    attach = tmp_path / "note.txt"
    attach.write_text("hi", encoding="utf-8")
    from kite.cli.run import build_parser, cmd_resume, main

    assert main(["chat", "--steps", "3", "--cost", "1.5", "--time", "9", "--role", "architect", "--long", "--attach", str(attach)]) == 0
    assert captured["step_limit"] == 3 and captured["role"] == "architect" and captured["attachments"]
    parser = build_parser()
    for flag in ("--headless", "--json", "--quiet", "--no-stream"):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["chat", flag])
        assert exc.value.code == 2
    monkeypatch.setattr("kite.ui.repl.ChatSession", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no start")))
    assert main(["chat", "--attach", "/definitely/missing"]) == 2
    from kite.application.contracts import RunResult
    from kite.memory.session import Session, SessionMeta

    meta = SessionMeta(id="abc12345", created_at=1.0, updated_at=1.0, cwd=".", provider="groq", model="x", task="t")
    monkeypatch.setattr("kite.memory.session.load_session", lambda *_a, **_k: Session(meta=meta))
    action = parser._subparsers._group_actions[0]
    resume = action.choices["resume"]
    assert cmd_resume(resume.parse_args(["abc12345", "--json"])) == 2
    seen: dict = {}

    def fake_build(**kwargs):
        seen.update(kwargs)
        return MagicMock()

    class FakeHarness:
        def __init__(self, config):
            self.config = config
            self.last_session = None

        def subscribe(self, *_a, **_k):
            return None

        def teardown_jobs(self):
            return None

    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", fake_build)
    monkeypatch.setattr("kite.agent.harness.Harness", FakeHarness)
    monkeypatch.setattr(
        "kite.application.cli.execute_harness_task",
        lambda *_a, **_k: RunResult(status="completed", stop_reason="submitted", final_message="ok", legacy={"exit_status": "Submitted", "submission": "ok"}),
    )
    out = tmp_path / "traj.json"
    args = resume.parse_args(["abc12345", "continue", "--time", "30", "--role", "debugger", "--output", str(out), "--json"])
    args.cwd = str(tmp_path)
    assert cmd_resume(args) == 0
    assert seen["wall_time_limit_seconds"] == 30 and seen["role"] == "debugger"
    import re

    from kite.cli.help_map import cli_help_brief, cli_help_text

    assert "kite help all" in cli_help_brief()
    text = cli_help_text()
    assert "kite_commands.md" in text and "CONTEXT.md" in text
    assert "kite-system-design" not in text
    flags = set(re.findall(r"--[a-z0-9-]+", text.split("Flags on run:")[-1]))
    combined = action.choices["run"].format_help() + action.choices["chat"].format_help() + resume.format_help() + action.choices["config"].format_help()
    assert [flag for flag in flags if flag not in combined] == []
    help_text_cli = parser.format_help()
    assert "maintainer" not in help_text_cli
    assert "models" not in help_text_cli
    assert "run" in help_text_cli
    assert parser.parse_args(["maintainer", "dashboard"]).command == "maintainer"
    from kite.cli.run import cmd_resume as _resume
    monkeypatch.setattr("kite.ui.pick.can_prompt", lambda: False)
    assert _resume(argparse.Namespace(session=None)) == 2


def test_headless_tasks_status_and_approval(monkeypatch, workspace, kite_home, capsys) -> None:
    task = parse_task_line("fix the tests", default_cwd="/tmp/ws")
    assert task and task.task == "fix the tests"
    json_task = parse_task_line('{"task": "scout auth", "label": "auth", "profile": "scout", "mode": "plan"}')
    assert json_task and json_task.label == "auth"
    tasks = load_tasks_text("# header\n\nrun tests\n\n{\"task\": \"lint\", \"label\": \"lint\"}\n", default_cwd=".")
    assert len(tasks) == 2
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_task_line("{not json}")
    assert resolve_headless_approval("approve", AgentMode.BUILD, headless=True) is ApprovalMode.APPROVE
    assert resolve_headless_approval(None, AgentMode.BUILD, headless=True) is ApprovalMode.AUTO
    assert is_headless_run(headless_flag=True, quiet=False)
    HeadlessRunDisplay(stream_tools=True)(Event("tool_start", payload={"tool": "bash", "arguments": {"command": "pytest -q"}}))
    assert "[tool]" in capsys.readouterr().err
    from kite.application.contracts import RunResult

    def fake_execute(harness, task):  # noqa: ANN001
        return RunResult(status="failed", stop_reason="error", final_message="", legacy={"exit_status": "Stalled", "submission": "", "error": "Stalled"})

    monkeypatch.setattr("kite.application.cli.execute_harness_task", fake_execute)
    stalled = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert stalled.ok is False and stalled.exit_status == "Stalled"

    def submitted(harness, task):  # noqa: ANN001
        return RunResult(status="completed", stop_reason="submitted", final_message="done", legacy={"exit_status": "Submitted", "submission": "done"})

    monkeypatch.setattr("kite.application.cli.execute_harness_task", submitted)
    ok = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert ok.ok is True

    def fake_run(task: HeadlessTask, **kwargs):
        from kite.tasks import HeadlessTaskResult

        return HeadlessTaskResult(index=0, label=task.label, ok=False, exit_status="ProviderFault", session_id="s1")

    monkeypatch.setattr("kite.tasks.run_headless_task", fake_run)
    batch = run_headless_batch([HeadlessTask(task="one", label="a")], continue_on_error=True)
    assert batch.ok is False and batch.to_dict()["succeeded"] == 0
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["tasks", "run", "tasks.jsonl", "--dry-run"])
    assert args.tasks_action == "run" and args.dry_run is True
    run_args = build_parser().parse_args(["run", "--headless", "--no-stream", "fix tests"])
    assert run_args.headless is True and run_args.task == "fix tests"


def test_headless_wires_noninteractive_approval(monkeypatch, workspace, kite_home) -> None:
    from kite.application.contracts import RunResult

    observed: list[str] = []

    def fake_execute(harness, task):  # noqa: ANN001
        observed.append(harness.approver("write", {"path": str(workspace / "generated.txt")}, {}))
        return RunResult(status="completed", stop_reason="submitted", final_message="done", legacy={"exit_status": "Submitted", "submission": "done"})

    monkeypatch.setattr("kite.application.cli.execute_harness_task", fake_execute)
    for approval, expected in (("auto", "allow"), ("readonly", "deny"), ("approve", "deny")):
        observed.clear()
        result = run_headless_task(HeadlessTask(task="generate a file", cwd=str(workspace), approval=approval))
        assert result.ok is True and observed == [expected]


def test_ci_workflows_run_ruff_pytest_and_bench() -> None:
    root = Path(__file__).resolve().parents[1]
    tests_yml = (root / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    release_yml = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for body in (tests_yml, release_yml):
        assert "ruff check src tests" in body
        assert "pytest -q" in body
        assert "bench --check" in body


def test_scripts_dir_keeps_only_supported_files() -> None:
    names = {p.name for p in Path(__file__).resolve().parents[1].joinpath("scripts").iterdir() if p.is_file()}
    assert names == {
        "bump_release.sh",
        "download.ps1",
        "download.sh",
        "install.ps1",
        "install.sh",
        "sync_version.py",
    }


def test_parser_skips_heavy_backend_imports() -> None:
    import sys

    from kite.cli.run import build_parser

    before = set(sys.modules)
    build_parser()
    added = set(sys.modules) - before
    assert "kite.cli.setup" not in added
    assert "kite.cli.dashboard" not in added
    assert "kite.bench.suite" not in added
    from kite.config import UserConfig, assess_setup_status

    assert UserConfig.load() is not None
    assert callable(assess_setup_status)
