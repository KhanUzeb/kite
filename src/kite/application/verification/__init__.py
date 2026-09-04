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
from kite.application.verification.workspace_profile import WorkspaceProfile, discover_workspace_profile

__all__ = [
    "CheckSpec",
    "EvidenceRecord",
    "EvidenceVerifier",
    "VerificationPlan",
    "VerificationRecord",
    "WorkspaceProfile",
    "build_verification_plan",
    "classify_path",
    "discover_workspace_profile",
    "plan_status",
]
