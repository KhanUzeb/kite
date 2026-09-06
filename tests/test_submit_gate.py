"""Submit gate and hallucination prevention tests."""

from __future__ import annotations

from kite.agent.exceptions import Submitted
from kite.agent.loop import DefaultAgent
from kite.agent.verification import VerificationCollector


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
    def execute(self, action: dict, cwd: str = "") -> dict:
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


def _vc_with_edit_and_test(passed: bool = True) -> VerificationCollector:
    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    vc.on_tool_end(
        "bash",
        {"command": "pytest -q"},
        {"ok": passed, "returncode": 0 if passed else 1, "output": "1 passed" if passed else "FAIL"},
    )
    return vc


def test_agent_submit_blocked_without_tests_after_edit() -> None:
    agent = DefaultAgent(_EditThenSubmitModel(), _StubEnv(), verify_before_submit=True, step_limit=3)
    agent.run("fix a.py")
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
    assert "Submit blocked" in blob
    assert agent.verification.has_edits() and not agent.verification.has_passing_tests()


def test_submit_gate_scenarios() -> None:
    submission = "## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ pytest -q"
    assert _vc_with_edit_and_test().submit_block_reason(submission) is None

    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "pytest"}, {"ok": False, "returncode": 1, "output": "FAIL"})
    assert vc.submit_block_reason() is not None

    vc = VerificationCollector()
    reason = vc.submit_block_reason("All tests pass and build succeeds.")
    assert reason and ("claims" in reason.lower() or "verification" in reason.lower())
    assert VerificationCollector().submit_block_reason("hello, all done!") is None

    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": "ls"}, {"ok": True, "returncode": 0, "output": "a.py"})
    assert vc.submit_block_reason("All tests pass.") and not vc.has_passing_tests()

    vc = _vc_with_edit_and_test(passed=False)
    assert vc.status() == "failed"
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    assert vc.has_passing_tests() and vc.submit_block_reason(submission) is None

    reason = VerificationCollector().unfounded_claim_reason("I finished the refactor and it should work.")
    assert reason and ("do not claim" in reason.lower() or "submit blocked" in reason.lower())
