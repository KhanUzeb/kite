"""Canonical event payload shapes for application-layer events."""

from __future__ import annotations

from typing import Any

from kite.application.verification import VerificationRecord


def verification_plan_payload(plan: Any) -> dict[str, Any]:
    return {
        "touched_paths": list(plan.touched_paths),
        "artifact_kinds": sorted(plan.artifact_kinds),
        "required_checks": [
            {
                "kind": c.kind,
                "command": c.command,
                "affected_paths": list(c.affected_paths),
                "artifact_kind": c.artifact_kind,
            }
            for c in plan.required_checks
        ],
    }


def verification_record_payload(record: VerificationRecord) -> dict[str, Any]:
    return {
        "command": record.command,
        "affected_paths": list(record.affected_paths),
        "exit_status": record.exit_status,
        "ok": record.ok,
        "output_summary": record.output_summary[:240],
        "satisfies": list(record.satisfies),
        "check_kind": record.check.kind,
        "artifact_kind": record.check.artifact_kind,
    }


def approval_request_payload(
    request_id: str,
    *,
    tool: str,
    reason: str,
    mandatory: bool = False,
    diff_preview: str = "",
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "tool": tool,
        "reason": reason,
        "mandatory": mandatory,
        "diff_preview": diff_preview[:400],
    }


def approval_decision_payload(request_id: str, decision: str, *, reason: str = "") -> dict[str, Any]:
    return {"request_id": request_id, "decision": decision, "reason": reason}


def submit_blocked_payload(reason: str, *, claim: str = "") -> dict[str, Any]:
    return {"reason": reason, "claim": claim[:400]}
