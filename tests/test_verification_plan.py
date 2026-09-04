"""Verification plan selection tests."""

from __future__ import annotations

from kite.application.verification.plan import (
    VerificationRecord,
    build_verification_plan,
    classify_path,
    plan_status,
    record_satisfies_check,
)
from kite.application.verification.plan import CheckSpec


def test_html_only_never_requires_pytest() -> None:
    plan = build_verification_plan(("dashboard.html",))
    assert "html" in plan.artifact_kinds
    assert all(
        c.command is None or "pytest" not in (c.command or "").lower()
        for c in plan.required_checks
    )
    assert plan.required_checks
    assert plan.required_checks[0].artifact_kind == "html"


def test_python_edit_selects_python_check() -> None:
    plan = build_verification_plan(("src/kite/foo.py",))
    assert plan.required_checks
    assert plan.required_checks[0].artifact_kind == "python"


def test_unknown_file_has_empty_required_checks() -> None:
    plan = build_verification_plan(("README",))
    assert plan.required_checks == ()
    assert plan_status(plan, []) == "changed_unverified"


def test_unrelated_pass_does_not_satisfy_html_check() -> None:
    plan = build_verification_plan(("index.html",))
    html_check = plan.required_checks[0]
    pytest_record = VerificationRecord(
        check=CheckSpec(kind="project_test", command="pytest -q", affected_paths=("a.py",), artifact_kind="python"),
        command="pytest -q",
        affected_paths=("a.py",),
        exit_status=0,
        ok=True,
        output_summary="1 passed",
    )
    assert not record_satisfies_check(pytest_record, html_check)


def test_classify_path_kinds() -> None:
    assert classify_path("x.py") == "python"
    assert classify_path("x.html") == "html"
    assert classify_path("x.md") == "docs"
