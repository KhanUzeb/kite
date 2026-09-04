"""Verification collector helpers — keeps VerificationCollector complexity low."""

from __future__ import annotations

import html.parser
import re
from typing import TYPE_CHECKING, Any

from kite.application.verification.plan import (
    CheckSpec,
    VerificationRecord,
    build_verification_plan,
    classify_path,
    plan_status,
)

if TYPE_CHECKING:
    from kite.agent.verification import Artifact, VerificationCollector, VerificationStatus

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
_TEST_GAP_PREFIX = "test command failed"

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


class _HtmlChecker(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parse_error: str | None = None

    def error(self, message: str) -> None:  # type: ignore[override]
        self.parse_error = message


def html_parse_ok(content: str) -> bool:
    if not content.strip():
        return True
    checker = _HtmlChecker()
    try:
        checker.feed(content)
        checker.close()
    except Exception:
        return False
    if checker.parse_error is not None:
        return False
    lowered = content.lower()
    if "<html" in lowered and "</html>" not in lowered:
        return False
    return True


def looks_like_test(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(h in lowered for h in _TEST_HINTS)


def latest_test(artifacts: list[Artifact]) -> Artifact | None:
    tests = [a for a in artifacts if a.kind == "test"]
    return tests[-1] if tests else None


def terminal_status(collector: VerificationCollector) -> VerificationStatus:
    latest = latest_test(collector.artifacts)
    if latest is not None and not latest.ok:
        return "failed"
    if collector.gaps:
        return "failed"
    if not collector.has_edits() and not collector.paths_touched:
        if latest is not None and latest.ok:
            return "verified"
        if collector.artifacts:
            return (
                "partial"
                if any(a.kind == "command" and a.ok for a in collector.artifacts)
                else "unverified"
            )
        return "idle"
    plan = collector.plan()
    st = plan_status(plan, collector._records)
    if st == "changed_unverified" and collector.has_edits():
        return "changed_unverified"
    return st  # type: ignore[return-value]


def record_html_check(collector: VerificationCollector, path: str, content: str) -> None:
    plan = collector.plan()
    for check in plan.required_checks:
        if check.artifact_kind != "html" or path not in check.affected_paths:
            continue
        ok = html_parse_ok(content) if content else True
        collector._records.append(
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


def _match_bash_check(cmd: str, plan) -> CheckSpec | None:
    lowered = cmd.lower()
    for check in plan.required_checks:
        if check.command and check.command.lower() in lowered:
            return check
        if check.artifact_kind == "python" and "pytest" in lowered:
            return check
    if plan.required_checks:
        return plan.required_checks[0]
    return None


def record_bash_check(
    collector: VerificationCollector,
    cmd: str,
    *,
    ok: bool,
    exit_code: int,
    preview: str,
    add_artifact: Any,
) -> None:
    if not looks_like_test(cmd):
        return
    plan = collector.plan()
    matched = _match_bash_check(cmd, plan)
    record = VerificationRecord(
        check=matched
        or CheckSpec(kind="project_test", command=cmd, affected_paths=(), artifact_kind="python"),
        command=cmd,
        affected_paths=matched.affected_paths if matched else (),
        exit_status=exit_code,
        ok=ok and exit_code == 0,
        output_summary=preview,
        satisfies=tuple(matched.affected_paths) if matched else (),
    )
    collector._records.append(record)
    add_artifact("test", f"exit={exit_code}  {cmd[:80]}", ok=record.ok, detail=preview)
    if record.ok:
        collector.gaps = [g for g in collector.gaps if not g.startswith(_TEST_GAP_PREFIX)]
    else:
        collector.gaps.append(f"{_TEST_GAP_PREFIX} (exit {exit_code}): {cmd[:80]}")


def apply_write_edit(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    if not result.get("ok"):
        return
    path = str(result.get("path") or args.get("path") or "")
    diff = str(result.get("diff") or "")
    content = str(result.get("content") or args.get("content") or "")
    if path:
        collector.paths_touched.add(path)
        if classify_path(path) == "html":
            record_html_check(collector, path, content or diff)
    if diff:
        collector.diffs.append(diff)
        add_artifact("diff", f"edited {path}", path=path, ok=True, detail=diff[:400])


def apply_read(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    if not result.get("ok"):
        return
    path = str(result.get("path") or args.get("path") or "")
    if path:
        collector.paths_read.add(path)
        add_artifact("read", f"read {path}", path=path, ok=True)


def apply_bash(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    cmd = str(args.get("command") or "")
    collector.last_bash_command = cmd
    rc = result.get("returncode")
    if rc is not None:
        collector.last_bash_exit = int(rc)
    ok = bool(result.get("ok"))
    preview = (str(result.get("output") or "")[:200]).replace("\n", " ")
    add_artifact("command", cmd[:120], ok=ok, detail=preview)
    record_bash_check(
        collector,
        cmd,
        ok=ok,
        exit_code=int(rc or (0 if ok else 1)),
        preview=preview,
        add_artifact=add_artifact,
    )


def unfounded_claim_reason(collector: VerificationCollector, text: str) -> str | None:
    body = (text or "").strip()
    if not body:
        return None
    verified = collector.has_passing_tests()
    if _EVIDENCE_CLAIM_RE.search(body) and not verified:
        return (
            "Submit blocked: summary claims tests/build passed but no passing verification command "
            "was recorded for the touched artifacts. Run the applicable check first."
        )
    if not _DONE_CLAIM_RE.search(body):
        return None
    if not collector.has_edits():
        return (
            "Do not claim the task is done. No edits or verification were recorded this session. "
            "Use tools, then submit with evidence — do not narrate completion."
        )
    plan = collector.plan()
    if plan.required_checks:
        if plan_status(plan, collector._records) != "verified":
            return (
                "Submit blocked: workspace was edited but required verification is incomplete. "
                "Run the applicable check for the changed files, then submit again."
            )
        return None
    return (
        "Submit blocked: workspace was edited but no passing test/lint command was recorded. "
        "Run the applicable check, then submit again."
    )


def _missing_verification_section(body: str) -> str | None:
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


def submit_block_reason(
    collector: VerificationCollector,
    submission: str = "",
    *,
    require_verification: bool = True,
    require_verification_section: bool = True,
) -> str | None:
    if not require_verification:
        return None
    plan = collector.plan()
    st = plan_status(plan, collector._records)
    if st == "failed" or collector.gaps:
        gap = collector.gaps[0] if collector.gaps else "a verification check failed"
        return f"Submit blocked: {gap}. Fix the failure and re-run verification before submitting."

    body = (submission or "").strip()
    if collector.has_edits() and plan.required_checks and st != "verified":
        kinds = ", ".join(sorted(plan.artifact_kinds))
        return (
            f"Submit blocked: workspace was edited ({kinds}) but required verification is incomplete. "
            "Run the applicable check for the changed files, then submit again."
        )

    claim = unfounded_claim_reason(collector, body)
    if claim:
        return claim

    if not (require_verification_section and collector.has_edits() and body and plan.required_checks):
        return None
    return _missing_verification_section(body)


def post_edit_nudge(collector: VerificationCollector) -> str | None:
    plan = build_verification_plan(tuple(sorted(collector.paths_touched)))
    if not collector.has_edits() or not plan.required_checks:
        return None
    if plan_status(plan, collector._records) == "verified":
        return None
    kinds = ", ".join(sorted(plan.artifact_kinds))
    if kinds == "html":
        return "[verification] HTML edited — structural parse will be checked; pytest is not required."
    return (
        f"[verification] Edits recorded ({kinds}) — run the applicable check for the changed files "
        "before submitting."
    )
