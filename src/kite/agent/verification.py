"""Task verification collector — artifact-aware plans and evidence records."""

from __future__ import annotations

import html.parser
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from kite.application.verification.plan import (
    CheckSpec,
    VerificationPlan,
    VerificationRecord,
    build_verification_plan,
    classify_path,
    plan_status,
    record_satisfies_check,
)

VerificationStatus = Literal[
    "verified", "partial", "unverified", "failed", "idle", "changed_unverified", "blocked"
]

_EVIDENCE_CLAIM_RE = re.compile(
    r"\b("
    r"tests?\s+pass(?:ed|ing)?|all\s+tests?\s+pass|"
    r"build\s+succeeds?|lint\s+clean|no\s+errors?|"
    r"fully\s+verified|confirmed\s+working|everything\s+works"
    r")\b",
    re.IGNORECASE,
)
_DONE_CLAIM_RE = re.compile(
    r"\b("
    r"task\s+complete|i(?:'ve| have)?\s+finished|"
    r"should\s+(?:work|pass)|looks\s+(?:good|fine)|"
    r"we(?:'re| are)\s+done|successfully\s+(?:implemented|fixed|completed)|"
    r"fully\s+implemented|all\s+good"
    r")\b",
    re.IGNORECASE,
)
_TEST_GAP_PREFIX = "test command failed"


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


class _HtmlChecker(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.error: str | None = None

    def error(self, message: str) -> None:  # type: ignore[override]
        self.error = message


def _html_parse_ok(content: str) -> bool:
    checker = _HtmlChecker()
    try:
        checker.feed(content)
        checker.close()
    except Exception:
        return False
    return checker.error is None


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
    _records: list[VerificationRecord] = field(default_factory=list, repr=False)

    _TEST_HINTS = (
        "pytest",
        "python -m pytest",
        "python -m unittest",
        "npm test",
        "go test",
        "cargo test",
        "ruff check",
        "mypy",
        "uv run pytest",
        "uv run ruff",
    )

    def plan(self) -> VerificationPlan:
        return build_verification_plan(tuple(sorted(self.paths_touched)))

    def _latest_test(self) -> Artifact | None:
        tests = [a for a in self.artifacts if a.kind == "test"]
        return tests[-1] if tests else None

    def _terminal_status(self) -> VerificationStatus:
        latest = self._latest_test()
        if latest is not None and not latest.ok:
            return "failed"
        if self.gaps:
            return "failed"
        if not self.has_edits() and not self.paths_touched:
            if latest is not None and latest.ok:
                return "verified"
            if self.artifacts:
                return "partial" if any(a.kind == "command" and a.ok for a in self.artifacts) else "unverified"
            return "idle"
        st = plan_status(self.plan(), self._records)
        if st == "changed_unverified" and self.has_edits():
            return "changed_unverified"
        return st  # type: ignore[return-value]

    def on_tool_end(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        if tool in {"write", "edit"} and result.get("ok"):
            path = str(result.get("path") or args.get("path") or "")
            diff = str(result.get("diff") or "")
            content = str(result.get("content") or args.get("content") or "")
            if path:
                self.paths_touched.add(path)
                if classify_path(path) == "html":
                    self._record_html_check(path, content or diff)
            if diff:
                self.diffs.append(diff)
                self._add("diff", f"edited {path}", path=path, ok=True, detail=diff[:400])
        if tool == "read" and result.get("ok"):
            path = str(result.get("path") or args.get("path") or "")
            if path:
                self.paths_read.add(path)
                self._add("read", f"read {path}", path=path, ok=True)
        if tool == "bash":
            cmd = str(args.get("command") or "")
            self.last_bash_command = cmd
            rc = result.get("returncode")
            if rc is not None:
                self.last_bash_exit = int(rc)
            ok = bool(result.get("ok"))
            preview = (str(result.get("output") or "")[:200]).replace("\n", " ")
            self._add("command", cmd[:120], ok=ok, detail=preview)
            self._record_bash_check(cmd, ok=ok, exit_code=int(rc or (0 if ok else 1)), preview=preview)

    def _record_html_check(self, path: str, content: str) -> None:
        plan = self.plan()
        for check in plan.required_checks:
            if check.artifact_kind != "html" or path not in check.affected_paths:
                continue
            ok = _html_parse_ok(content) if content else True
            self._records.append(
                VerificationRecord(
                    check=check,
                    command="html-parse",
                    affected_paths=(path,),
                    exit_status=0 if ok else 1,
                    ok=ok,
                    output_summary="structural parse ok" if ok else "html parse failed",
                    satisfies=(path,),
                )
            )

    def _record_bash_check(self, cmd: str, *, ok: bool, exit_code: int, preview: str) -> None:
        lowered = cmd.lower()
        is_testish = any(h in lowered for h in self._TEST_HINTS)
        plan = self.plan()
        matched_check: CheckSpec | None = None
        if is_testish:
            for check in plan.required_checks:
                if check.command and check.command.lower() in lowered:
                    matched_check = check
                    break
                if check.artifact_kind == "python" and "pytest" in lowered:
                    matched_check = check
                    break
            if matched_check is None and plan.required_checks:
                matched_check = plan.required_checks[0]
        if is_testish:
            record = VerificationRecord(
                check=matched_check
                or CheckSpec(kind="project_test", command=cmd, affected_paths=(), artifact_kind="python"),
                command=cmd,
                affected_paths=matched_check.affected_paths if matched_check else (),
                exit_status=exit_code,
                ok=ok and exit_code == 0,
                output_summary=preview,
                satisfies=tuple(matched_check.affected_paths) if matched_check else (),
            )
            self._records.append(record)
            self._add("test", f"exit={exit_code}  {cmd[:80]}", ok=record.ok, detail=preview)
            if record.ok:
                self.gaps = [g for g in self.gaps if not g.startswith(_TEST_GAP_PREFIX)]
            else:
                self.gaps.append(f"{_TEST_GAP_PREFIX} (exit {exit_code}): {cmd[:80]}")

    def _add(self, kind: str, summary: str, **kw: Any) -> None:
        self.artifacts.append(Artifact(kind=kind, summary=summary, **kw))

    def has_edits(self) -> bool:
        return bool(self.diffs or self.paths_touched)

    def has_passing_tests(self) -> bool:
        latest = self._latest_test()
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
        return self._terminal_status()

    def unfounded_claim_reason(self, text: str) -> str | None:
        body = (text or "").strip()
        if not body:
            return None
        verified = self.has_passing_tests()
        if _EVIDENCE_CLAIM_RE.search(body) and not verified:
            return (
                "Submit blocked: summary claims tests/build passed but no passing verification command "
                "was recorded for the touched artifacts. Run the applicable check first."
            )
        if _DONE_CLAIM_RE.search(body) and not verified:
            if self.has_edits():
                plan = self.plan()
                if plan.required_checks and plan_status(plan, self._records) != "verified":
                    return (
                        "Submit blocked: workspace was edited but required verification is incomplete. "
                        "Run the applicable check for the changed files, then submit again."
                    )
                if plan.required_checks:
                    return None
                return (
                    "Submit blocked: workspace was edited but no passing test/lint command was recorded. "
                    "Run the applicable check, then submit again."
                )
            return (
                "Do not claim the task is done. No edits or verification were recorded this session. "
                "Use tools, then submit with evidence — do not narrate completion."
            )
        return None

    def has_work(self) -> bool:
        return bool(self.artifacts or self.diffs or self.gaps)

    def submit_block_reason(
        self,
        submission: str = "",
        *,
        require_verification: bool = True,
        require_verification_section: bool = True,
    ) -> str | None:
        if not require_verification:
            return None
        plan = self.plan()
        st = plan_status(plan, self._records)
        if st == "failed" or self.gaps:
            gap = self.gaps[0] if self.gaps else "a verification check failed"
            return f"Submit blocked: {gap}. Fix the failure and re-run verification before submitting."

        body = (submission or "").strip()
        if self.has_edits() and plan.required_checks and plan_status(plan, self._records) != "verified":
            kinds = ", ".join(sorted(plan.artifact_kinds))
            return (
                f"Submit blocked: workspace was edited ({kinds}) but required verification is incomplete. "
                "Run the applicable check for the changed files, then submit again."
            )

        claim = self.unfounded_claim_reason(body)
        if claim:
            return claim

        if require_verification_section and self.has_edits() and body and plan.required_checks:
            if "## verification" not in body.lower():
                return (
                    "Submit blocked: include a ## Verification section listing commands you ran "
                    "(e.g. `- ✓ pytest -q`). Do not claim done without checkable evidence."
                )
            if not re.search(r"[-*]\s*✓", body):
                return (
                    "Submit blocked: ## Verification must list at least one checked item "
                    "(e.g. `- ✓ pytest -q — 42 passed`)."
                )
        return None

    def post_edit_nudge(self) -> str | None:
        plan = self.plan()
        if not self.has_edits() or not plan.required_checks:
            return None
        if plan_status(plan, self._records) == "verified":
            return None
        kinds = ", ".join(sorted(plan.artifact_kinds))
        if kinds == "html":
            return "[verification] HTML edited — structural parse will be checked; pytest is not required."
        return (
            f"[verification] Edits recorded ({kinds}) — run the applicable check for the changed files "
            "before submitting."
        )

    def summary(self) -> dict[str, Any]:
        plan = self.plan()
        st = self.status()
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
