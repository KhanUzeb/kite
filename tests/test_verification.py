"""Verification collector — test command detection."""

from __future__ import annotations

from kite.agent.verification import VerificationCollector


def test_detects_pytest_as_test_artifact() -> None:
    vc = VerificationCollector()
    vc.on_tool_end(
        "bash",
        {"command": "pytest tests/ -q"},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    kinds = [a.kind for a in vc.artifacts]
    assert "test" in kinds
    assert vc.status() == "verified"


def test_failed_test_marks_gap() -> None:
    vc = VerificationCollector()
    vc.on_tool_end(
        "bash",
        {"command": "uv run pytest"},
        {"ok": False, "returncode": 1, "output": "FAILED"},
    )
    assert vc.status() == "failed"
    assert vc.gaps


def test_empty_run_is_idle() -> None:
    vc = VerificationCollector()
    assert vc.status() == "idle"
    assert vc.has_work() is False
    assert vc.summary()["status"] == "idle"


def test_edits_without_tests_need_verification() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "x.py"}, {"ok": True, "path": "x.py", "diff": "d"})
    assert vc.needs_tests() is True
    reason = vc.submit_block_reason("## Done\nx\n## Changed\n`x.py`\n## Verification\n- ✓ ok")
    assert reason is not None


def test_python_m_pytest_detected() -> None:
    vc = VerificationCollector()
    vc.on_tool_end(
        "bash",
        {"command": "python -m pytest tests/ -q"},
        {"ok": True, "returncode": 0, "output": "ok"},
    )
    assert any(a.kind == "test" for a in vc.artifacts)


def test_post_edit_nudge() -> None:
    vc = VerificationCollector()
    vc.on_tool_end("write", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    nudge = vc.post_edit_nudge()
    assert nudge is not None
    assert "verification" in nudge.lower()


def test_unfounded_done_claim() -> None:
    vc = VerificationCollector()
    reason = vc.unfounded_claim_reason("Task complete — looks fine.")
    assert reason is not None
    assert vc.submit_block_reason("hello, all done!") is None
