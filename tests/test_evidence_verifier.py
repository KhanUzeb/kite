"""Evidence verification tests."""

from __future__ import annotations

from kite.application.tools import ToolResult
from kite.application.verification import EvidenceVerifier


def test_evidence_from_passing_pytest() -> None:
    v = EvidenceVerifier("run-1")
    result = ToolResult(
        call_id="c1",
        status="ok",
        ok=True,
        output="3 passed",
        metadata={"command": "pytest -q", "exit_code": 0},
    )
    record = v.consume(result, command="pytest -q", cwd="/proj")
    assert record is not None
    assert record.status == "passed"
    status = v.verification_status()
    assert status["status"] == "verified"


def test_model_claim_without_evidence_fails() -> None:
    v = EvidenceVerifier("run-2")
    assert not v.model_claim_satisfies("All tests pass!")


def test_model_claim_with_evidence() -> None:
    v = EvidenceVerifier("run-3")
    v.consume(
        ToolResult(call_id="c1", status="ok", ok=True, metadata={"command": "pytest", "exit_code": 0}),
        command="pytest",
    )
    assert v.model_claim_satisfies("tests pass")
