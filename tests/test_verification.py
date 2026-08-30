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
