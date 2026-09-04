"""Task verification collector — artifact-aware plans and evidence records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from kite.application.verification.collector_ops import (
    apply_bash,
    apply_read,
    apply_write_edit,
    terminal_status,
)
from kite.application.verification.collector_ops import (
    post_edit_nudge as _post_edit_nudge,
)
from kite.application.verification.collector_ops import (
    submit_block_reason as _submit_block_reason,
)
from kite.application.verification.collector_ops import (
    unfounded_claim_reason as _unfounded_claim_reason,
)
from kite.application.verification.plan import (
    VerificationRecord,
    build_verification_plan,
    plan_status,
)
from kite.application.verification.evidence import EvidenceVerifier, is_check_command
from kite.application.verification.workspace_profile import WorkspaceProfile, discover_workspace_profile
from kite.application.tools.contracts import ToolResult

VerificationStatus = Literal[
    "verified", "partial", "unverified", "failed", "idle", "changed_unverified", "blocked"
]


@dataclass
class Artifact:
    kind: str
    summary: str
    path: str = ""
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "path": self.path,
            "ok": self.ok,
            "detail": self.detail[:500] if self.detail else "",
        }


@dataclass
class VerificationCollector:
    """Accumulates checkable evidence during a run."""

    artifacts: list[Artifact] = field(default_factory=list)
    last_bash_exit: int | None = None
    last_bash_command: str = ""
    diffs: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    paths_touched: set[str] = field(default_factory=set)
    paths_read: set[str] = field(default_factory=set)
    workspace_root: str = ""
    run_id: str = ""
    _workspace_profile: WorkspaceProfile | None = field(default=None, repr=False)
    _records: list[VerificationRecord] = field(default_factory=list, repr=False)
    _evidence: EvidenceVerifier | None = field(default=None, repr=False)

    def _evidence_verifier(self) -> EvidenceVerifier:
        if self._evidence is None:
            self._evidence = EvidenceVerifier(self.run_id or "run")
        return self._evidence

    def _profile(self) -> WorkspaceProfile | None:
        if self._workspace_profile is not None:
            return self._workspace_profile
        if not self.workspace_root:
            return None
        self._workspace_profile = discover_workspace_profile(self.workspace_root)
        return self._workspace_profile

    def plan(self):
        return build_verification_plan(tuple(sorted(self.paths_touched)), profile=self._profile())

    def on_tool_end(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        if tool in {"write", "edit"}:
            apply_write_edit(self, args, result, self._add)
        elif tool == "read":
            apply_read(self, args, result, self._add)
        elif tool == "bash":
            apply_bash(self, args, result, self._add)
            cmd = str(args.get("command") or "")
            if cmd and is_check_command(cmd):
                rc = int(result.get("returncode") or (0 if result.get("ok") else 1))
                self._evidence_verifier().consume(
                    ToolResult(
                        call_id=str(result.get("call_id") or cmd[:32]),
                        status="ok" if result.get("ok") else "error",
                        ok=bool(result.get("ok")),
                        output=str(result.get("output") or ""),
                        error=str(result.get("error") or ""),
                        metadata={"command": cmd, "exit_code": rc},
                    ),
                    command=cmd,
                    cwd=self.workspace_root,
                )

    def _add(self, kind: str, summary: str, **kw: Any) -> None:
        self.artifacts.append(Artifact(kind=kind, summary=summary, **kw))

    def has_edits(self) -> bool:
        return bool(self.diffs or self.paths_touched)

    def has_passing_tests(self) -> bool:
        from kite.application.verification.collector_ops import latest_test

        latest = latest_test(self.artifacts)
        if latest is not None and latest.ok:
            return True
        plan = self.plan()
        if plan.required_checks:
            return plan_status(plan, self._records) == "verified"
        return False

    def needs_tests(self) -> bool:
        plan = self.plan()
        if not self.has_edits() or not plan.required_checks:
            return False
        return plan_status(plan, self._records) != "verified"

    def status(self) -> VerificationStatus:
        return terminal_status(self)

    def unfounded_claim_reason(self, text: str) -> str | None:
        return _unfounded_claim_reason(self, text)

    def has_work(self) -> bool:
        return bool(self.artifacts or self.diffs or self.gaps)

    def submit_block_reason(
        self,
        submission: str = "",
        *,
        require_verification: bool = True,
        require_verification_section: bool = True,
    ) -> str | None:
        return _submit_block_reason(
            self,
            submission,
            require_verification=require_verification,
            require_verification_section=require_verification_section,
        )

    def post_edit_nudge(self) -> str | None:
        return _post_edit_nudge(self)

    def summary(self) -> dict[str, Any]:
        plan = self.plan()
        st = self.status()
        evidence = self._evidence_verifier().verification_status()
        return {
            "status": st,
            "artifact_count": len(self.artifacts),
            "diff_count": len(self.diffs),
            "gaps": list(self.gaps),
            "artifacts": [a.to_dict() for a in self.artifacts[-12:]],
            "last_bash_exit": self.last_bash_exit,
            "paths_touched": sorted(self.paths_touched)[-16:],
            "artifact_kinds": sorted(plan.artifact_kinds),
            "required_checks": len(plan.required_checks),
            "evidence_records": len(self._records),
            "evidence": evidence,
            "workspace_root": plan.workspace_root,
            "package_count": plan.package_count,
        }

    def render_lines(self) -> list[str]:
        st = self.status()
        lines = [f"verification: {st}"]
        for a in self.artifacts[-8:]:
            mark = "✓" if a.ok else "✗"
            lines.append(f"  {mark} [{a.kind}] {a.summary}")
        for g in self.gaps:
            lines.append(f"  ⚠ {g}")
        return lines
