"""Policy, tools, and execution safety tests."""

from __future__ import annotations

from pathlib import Path

from kite.application.execution import ChangeJournal, ProcessRunner, ToolExecutor
from kite.application.policy import PolicyEngine, check_path_access
from kite.application.tools import ToolCall


def test_path_blocks_traversal(workspace: Path) -> None:
    ok, reason = check_path_access("../outside", workspace)
    assert not ok
    assert "outside" in reason.lower() or "workspace" in reason.lower()


def test_path_allows_workspace_file(workspace: Path) -> None:
    ok, _ = check_path_access("src/app.py", workspace)
    assert ok


def test_policy_blocks_network_bash_in_restricted(workspace: Path) -> None:
    engine = PolicyEngine(workspace, execution_mode="restricted")
    call = ToolCall(call_id="1", name="bash", arguments={"command": "curl http://evil.com"})
    intent = engine.derive_intent(call)
    decision = engine.authorize(intent)
    assert not decision.allowed


def test_tool_executor_denied_without_approval(workspace: Path) -> None:
    engine = PolicyEngine(workspace)
    executor = ToolExecutor(
        policy=engine,
        runner=lambda c: {"ok": True, "output": "done"},
        approver=lambda i, d: False,
    )
    call = ToolCall(call_id="w1", name="write", arguments={"path": "src/app.py", "content": "x"})
    result = executor.execute(call)
    assert result.status == "denied"


def test_change_journal_restore_conflict(workspace: Path) -> None:
    target = workspace / "src" / "app.py"
    original = target.read_bytes()
    journal = ChangeJournal(workspace)
    journal.record_write(target)
    target.write_text("agent edit\n", encoding="utf-8")
    journal.record_after_write(target)
    target.write_text("user edit\n", encoding="utf-8")
    restored, conflicts = journal.restore()
    assert conflicts
    assert target.read_text(encoding="utf-8") == "user edit\n"


def test_change_journal_restore_clean(workspace: Path) -> None:
    target = workspace / "src" / "app.py"
    original = target.read_text(encoding="utf-8")
    journal = ChangeJournal(workspace)
    journal.record_write(target)
    target.write_text("agent only\n", encoding="utf-8")
    journal.record_after_write(target)
    restored, conflicts = journal.restore()
    assert not conflicts
    assert target.read_text(encoding="utf-8") == original


def test_process_runner_echo() -> None:
    runner = ProcessRunner(timeout_seconds=5.0)
    import sys

    if sys.platform == "win32":
        result = runner.run(["cmd", "/c", "echo", "hi"])
    else:
        result = runner.run(["echo", "hi"])
    assert result.exit_code == 0
    assert "hi" in result.stdout
