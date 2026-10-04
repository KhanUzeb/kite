"""Task verification collector — artifact-aware plans and evidence records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from kite.application.tools import ToolResult
from kite.application.verification import (
    MAX_BLOCKED_SUBMITS,
    CheckFailure,
    EvidenceVerifier,
    VerificationRecord,
    WorkspaceProfile,
    apply_bash,
    apply_read,
    apply_write_edit,
    build_verification_plan,
    discover_workspace_profile,
    is_check_command,
    normalize_check_command,
    plan_status,
    terminal_status,
)
from kite.application.verification import (
    post_edit_nudge as _post_edit_nudge,
)
from kite.application.verification import (
    submit_block_reason as _submit_block_reason,
)
from kite.application.verification import (
    unfounded_claim_reason as _unfounded_claim_reason,
)

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
    failures: list[CheckFailure] = field(default_factory=list)
    paths_touched: set[str] = field(default_factory=set)
    paths_read: set[str] = field(default_factory=set)
    workspace_root: str = ""
    run_id: str = ""
    blocked_submits: int = 0
    blocked_signature: str = ""
    blocked_turn: int = -1
    gate_turn: int = 0
    _workspace_profile: WorkspaceProfile | None = field(default=None, repr=False)
    _records: list[VerificationRecord] = field(default_factory=list, repr=False)
    _evidence: EvidenceVerifier | None = field(default=None, repr=False)

    # -- failing checks -------------------------------------------------
    @property
    def gaps(self) -> list[str]:
        """Human-readable failing checks (kept for summaries and UI lines)."""
        return [f.text for f in self.failures]

    @gaps.setter
    def gaps(self, values: Iterable[str]) -> None:
        self.failures = [CheckFailure(detail=str(v)) for v in values]

    def record_failure(self, failure: CheckFailure) -> None:
        """Track the newest failure per command — a later pass clears it."""
        if failure.command:
            key = normalize_check_command(failure.command)
            self.failures = [f for f in self.failures if normalize_check_command(f.command) != key]
        self.failures.append(failure)

    def clear_failure(self, command: str) -> None:
        key = normalize_check_command(command)
        self.failures = [f for f in self.failures if normalize_check_command(f.command) != key]

    # -- submit gate bookkeeping ---------------------------------------
    def begin_turn(self) -> None:
        """Mark a new model turn — one turn spends one retry, however often the
        loop and the `submit` tool both consult the gate for it."""
        self.gate_turn += 1

    def note_submit_block(self, reason: str) -> int:
        """Record a blocked submit and return the streak length.

        A different reason means the model learned something new, so the streak
        restarts rather than inheriting an old attempt's penalty.
        """
        signature = hashlib.sha1(reason.encode()).hexdigest()[:12]
        if signature != self.blocked_signature:
            # New information — the streak restarts rather than inheriting an
            # earlier failure's penalty.
            self.blocked_submits = 0
        elif self.blocked_turn == self.gate_turn:
            # Same turn re-gating the same reason (loop + `submit` tool): one
            # attempt, one retry.
            return self.blocked_submits
        self.blocked_signature = signature
        self.blocked_turn = self.gate_turn
        self.blocked_submits += 1
        return self.blocked_submits

    def clear_submit_blocks(self) -> None:
        self.blocked_submits = 0
        self.blocked_signature = ""
        self.blocked_turn = -1

    @property
    def submit_exhausted(self) -> bool:
        """True once every retry is spent — the run should stop, not loop."""
        return self.blocked_submits >= MAX_BLOCKED_SUBMITS

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
        from kite.application.verification import latest_test

        plan = self.plan()
        if self.has_edits() and plan.required_checks:
            return plan_status(plan, self._records) == "verified"
        latest = latest_test(self.artifacts)
        if latest is not None and latest.ok:
            return True
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
        structured: bool = True,
    ) -> str | None:
        return _submit_block_reason(
            self,
            submission,
            require_verification=require_verification,
            require_verification_section=require_verification_section,
            structured=structured,
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
            "failures": [f.to_dict() for f in self.failures[-6:]],
            "blocked_submits": self.blocked_submits,
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
        # Newest first and capped — this text is re-injected into the model's
        # context on every blocked submit, so an unbounded list is a token leak.
        for f in reversed(self.failures[-4:]):
            mark = "⚠" if f.unfixable else "✗"
            note = " (cannot be fixed by retrying)" if f.unfixable else ""
            lines.append(f"  {mark} {f.text}{note}")
        return lines
