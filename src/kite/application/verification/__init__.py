"""Evidence-based verification."""

from kite.application.verification.evidence import EvidenceRecord, EvidenceVerifier
from kite.application.verification.plan import (
    CheckSpec,
    VerificationPlan,
    VerificationRecord,
    build_verification_plan,
    classify_path,
    plan_status,
)

__all__ = [
    "CheckSpec",
    "EvidenceRecord",
    "EvidenceVerifier",
    "VerificationPlan",
    "VerificationRecord",
    "build_verification_plan",
    "classify_path",
    "plan_status",
]
