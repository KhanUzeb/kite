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


def test_path_blocks_sibling_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "proj"
    evil = tmp_path / "proj-evil"
    workspace.mkdir()
    evil.mkdir()
    (workspace / "ok.txt").write_text("x\n", encoding="utf-8")
    (evil / "secret.txt").write_text("no\n", encoding="utf-8")
    ok, reason = check_path_access(evil / "secret.txt", workspace)
    assert not ok
    assert "sibling" in reason or "outside" in reason.lower()


def test_host_mode_allows_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "proj"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    target = other / "file.txt"
    target.write_text("ok\n", encoding="utf-8")
    allowed, _ = check_path_access(target, workspace, execution_mode="host")
    assert allowed
    blocked, _ = check_path_access(target, workspace, execution_mode="restricted")
    assert not blocked


def test_change_journal_user_delete_is_conflict(workspace: Path) -> None:
    target = workspace / "src" / "app.py"
    journal = ChangeJournal(workspace)
    journal.record_write(target)
    target.write_text("agent only\n", encoding="utf-8")
    journal.record_after_write(target)
    target.unlink()
    restored, conflicts = journal.restore()
    assert conflicts
    assert not restored
    assert not target.exists()


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


def test_tool_executor_skip_approval(workspace: Path) -> None:
    engine = PolicyEngine(workspace)
    executor = ToolExecutor(
        policy=engine,
        runner=lambda c: {"ok": True, "output": "done"},
        approver=lambda i, d: False,
    )
    call = ToolCall(call_id="w2", name="write", arguments={"path": "src/app.py", "content": "x"})
    result = executor.execute(call, skip_approval=True)
    assert result.ok


def test_tool_executor_propagates_submitted(workspace: Path) -> None:
    from kite.agent.exceptions import Submitted

    engine = PolicyEngine(workspace)

    def _runner(_call: ToolCall) -> dict:
        raise Submitted({"role": "exit", "content": "done", "extra": {"exit_status": "Submitted"}})

    executor = ToolExecutor(policy=engine, runner=_runner)
    call = ToolCall(call_id="s1", name="read", arguments={"path": "src/app.py"})
    try:
        executor.execute(call, skip_approval=True)
        raise AssertionError("expected Submitted")
    except Submitted:
        pass


def test_tool_executor_preserves_returncode(workspace: Path) -> None:
    engine = PolicyEngine(workspace)
    executor = ToolExecutor(
        policy=engine,
        runner=lambda c: {"ok": False, "returncode": 2, "output": "fail", "error": "fail"},
    )
    call = ToolCall(call_id="b1", name="bash", arguments={"command": "pytest -q"})
    result = executor.execute(call, skip_approval=True)
    assert result.metadata.get("returncode") == 2


def test_change_journal_restore_conflict(workspace: Path) -> None:
    target = workspace / "src" / "app.py"
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
