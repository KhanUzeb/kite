"""Submit gate and hallucination prevention tests."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import Submitted
from kite.agent.loop import DefaultAgent
from kite.agent.verification import VerificationCollector


class _SubmitModel:
    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": [
                    {
                        "tool": "bash",
                        "id": "call_1",
                        "arguments": {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n## Done\n- x"},
                    }
                ],
                "cost": 0.0,
            },
        }

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [{"role": "tool", "tool_call_id": "call_1", "content": str(outputs)}]


class _EditThenSubmitModel:
    def __init__(self) -> None:
        self.step = 0

    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
        self.step += 1
        if self.step == 1:
            return {
                "role": "assistant",
                "content": "",
                "extra": {
                    "actions": [
                        {"tool": "edit", "id": "e1", "arguments": {"path": "a.py", "old_string": "a", "new_string": "b"}},
                    ],
                    "cost": 0.0,
                },
            }
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": [
                    {
                        "tool": "bash",
                        "id": "call_1",
                        "arguments": {
                            "command": (
                                "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n"
                                "## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ done"
                            )
                        },
                    }
                ],
                "cost": 0.0,
            },
        }

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [{"role": "tool", "tool_call_id": "call_1", "content": str(outputs)}]


class _StubEnv:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, action: dict, cwd: str = "") -> dict:
        self.calls.append(action)
        tool = action.get("tool")
        if tool == "edit":
            return {"ok": True, "path": "a.py", "diff": "--- a\n+++ b", "output": "edited"}
        cmd = str((action.get("arguments") or {}).get("command") or "")
        if "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in cmd:
            raise Submitted(
                {
                    "role": "exit",
                    "content": "submitted",
                    "extra": {"exit_status": "Submitted", "submission": cmd},
                }
            )
        return {"ok": True, "output": ""}


def test_submit_blocked_without_tests_after_edit() -> None:
    agent = DefaultAgent(
        _EditThenSubmitModel(),
        _StubEnv(),
        verify_before_submit=True,
        step_limit=3,
    )
    agent.run("fix a.py")
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Submit blocked" in blob
    assert agent.verification.has_edits()
    assert not agent.verification.has_passing_tests()


def test_submit_allowed_with_passing_test() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    submission = "## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ pytest -q"
    assert vc.submit_block_reason(submission) is None


def test_submit_blocked_on_failed_tests() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "pytest"}, {"ok": False, "returncode": 1, "output": "FAIL"})
    assert vc.submit_block_reason() is not None


def test_submit_blocked_on_unfounded_claim() -> None:
    vc = VerificationCollector()
    reason = vc.submit_block_reason("All tests pass and build succeeds.")
    assert reason is not None
    assert "claims" in reason.lower() or "verification" in reason.lower()


def test_idle_chat_submit_not_blocked() -> None:
    vc = VerificationCollector()
    assert vc.submit_block_reason("hello, all done!") is None


def test_ls_does_not_count_as_test_evidence() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "ls"}, {"ok": True, "returncode": 0, "output": "a.py"})
    reason = vc.submit_block_reason("All tests pass.")
    assert reason is not None
    assert vc.status() == "partial"
    assert not vc.has_passing_tests()


def test_failed_then_passing_test_allows_submit() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": False, "returncode": 1, "output": "FAIL"})
    assert vc.status() == "failed"
    assert not vc.has_passing_tests()
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    assert vc.has_passing_tests()
    assert vc.status() == "verified"
    submission = "## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ pytest -q"
    assert vc.submit_block_reason(submission) is None


def test_passing_then_failing_test_blocks_submit() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "pytest"}, {"ok": True, "returncode": 0, "output": "ok"})
    vc.on_tool_end("bash", {"command": "pytest"}, {"ok": False, "returncode": 1, "output": "FAIL"})
    assert vc.status() == "failed"
    assert not vc.has_passing_tests()
    assert vc.submit_block_reason() is not None


def test_done_claim_without_work_is_unfounded() -> None:
    vc = VerificationCollector()
    reason = vc.unfounded_claim_reason("I finished the refactor and it should work.")
    assert reason is not None
    assert "do not claim" in reason.lower() or "submit blocked" in reason.lower()
