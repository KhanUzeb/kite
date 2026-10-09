"""Submit gate (hallucination trigger) — regression locks.

The gate is the mechanism that stops the model claiming work is done without
evidence. These tests drive it the way `src/kite/agent/loop.py` does: the
`submit` tool path (`structured=True`) and the marker/prose path
(`structured=False`). Nothing here weakens the gate — every test asserts a
block where the evidence does not support the claim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.agent.verification import VerificationCollector

REPORT = (
    "## Done\n- fixed the gate\n\n"
    "## Changed\n- `src/app.py`\n\n"
    "## Verification\n- ✓ pytest -q"
)


@pytest.fixture(autouse=True)
def _python_tests(workspace: Path, kite_home) -> None:
    """Extend the shared workspace with the test file the planner should select."""
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_app.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )


def _edited(workspace: Path, path: str = "src/app.py") -> VerificationCollector:
    """A collector that has really edited `path` (so the gate applies)."""
    vc = VerificationCollector(workspace_root=str(workspace))
    vc.on_tool_end("edit", {"path": path}, {"ok": True, "path": path, "diff": "d"})
    return vc


def _plan_command(workspace: Path) -> str:
    vc = _edited(workspace)
    checks = vc.plan().required_checks
    assert checks, "expected a required check for an edited python file"
    return checks[0].command or ""


# --- 1. well-formed report passes; bare claim is blocked --------------------


def test_well_formed_report_passes_after_the_check_runs(workspace: Path) -> None:
    """Done + Changed + Verification with a ✓ clears the gate once evidence exists."""
    ws = workspace
    vc = _edited(ws)
    assert vc.plan().required_checks
    # No evidence yet — a hallucinated "done" must not go through.
    assert vc.submit_block_reason(REPORT) is not None
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": _plan_command(ws)},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    assert vc.submit_block_reason(REPORT) is None


def test_bare_done_claim_without_sections_is_blocked(workspace: Path) -> None:
    """`I fixed it` with no sections is blocked on every gated path."""
    ws = workspace
    for structured in (True, False):
        vc = _edited(ws)
        vc.begin_turn()
        reason = vc.submit_block_reason("I fixed it.", structured=structured)
        assert reason is not None, f"bare claim passed (structured={structured})"
        assert "Submit blocked" in reason


def test_incomplete_report_shape_is_blocked(workspace: Path) -> None:
    """Evidence cannot substitute for required sections and checked items."""
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": _plan_command(ws)},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    reports = (
        "## Done\n- fixed\n\n## Changed\n- `src/app.py`\n\n## Verification\n- ran the tests",
        "## Done\n- fixed\n\n## Verification\n- ✓ pytest -q",
        "## Changed\n- `src/app.py`\n\n## Verification\n- ✓ pytest -q",
    )
    for report in reports:
        vc.begin_turn()
        assert vc.submit_block_reason(report) is not None


# --- 2. evidence must support the claim -----------------------------------


def test_unrelated_passing_test_does_not_satisfy_evidence(workspace: Path) -> None:
    """v1.0.5 contract: an unrelated green test run is not evidence for these edits.

    The planner wants a check scoped to the edited file. A run of a different
    test file must not satisfy it, or the model can claim done on the strength
    of a suite that never touched its change.
    """
    ws = workspace
    (ws / "tests" / "test_unrelated.py").write_text(
        "def test_unrelated():\n    assert True\n", encoding="utf-8"
    )
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": "pytest -q tests/test_unrelated.py"},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    reason = vc.submit_block_reason(REPORT)
    assert reason is not None, "an unrelated passing test satisfied the gate"
    assert "Submit blocked" in reason


def test_failing_check_blocks_the_claim(workspace: Path) -> None:
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": _plan_command(ws)},
        {"ok": False, "returncode": 1, "output": "FAILED tests/test_app.py::test_x - AssertionError"},
    )
    reason = vc.submit_block_reason(REPORT)
    assert reason is not None and "Suggested command" in reason


def test_verified_report_may_still_disclose_a_failure(workspace: Path) -> None:
    """A `## Blocked` section is the sanctioned honest exit — unchanged."""
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": _plan_command(ws)},
        {"ok": False, "returncode": 9009, "output": "pytest is not recognized"},
    )
    honest = (
        "## Done\n- fixed\n\n## Changed\n- `src/app.py`\n\n"
        "## Verification\n- ✗ pytest -q — runner missing\n\n## Blocked\n- pytest not installed"
    )
    assert vc.submit_block_reason(honest) is None


# --- 3. the gate reads the whole accumulated answer ------------------------


def test_gate_judges_the_full_report_not_a_truncated_prefix(workspace: Path) -> None:
    """A report whose evidence section sits past any UI tail is still judged.

    `submit_block_reason` receives the assistant message content verbatim; the
    render layer's `_STREAM_TAIL_CHARS` / `_already_shown` never reach it. A long
    preamble in front of the sections must not change the verdict.
    """
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": _plan_command(ws)},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    padded = ("## Done\n- fixed\n\n## Changed\n- `src/app.py`\n\n## Verification\n- ✓ pytest -q")
    long_prefix = "Here is a lot of narrative. " * 400
    assert vc.submit_block_reason(f"{long_prefix}\n\n{padded}") is None

    blocked = _edited(ws)
    blocked.begin_turn()
    assert blocked.submit_block_reason(f"{long_prefix}\n\nI fixed it.") is not None


# --- 4. verify_before_submit=False is the only bypass ----------------------


def test_gate_bypassed_only_when_verification_is_disabled(workspace: Path) -> None:
    """`require_verification=False` is the sanctioned off switch; default holds."""
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    assert vc.submit_block_reason(REPORT, require_verification=True) is not None
    assert vc.submit_block_reason(REPORT, require_verification=False) is None
    assert vc.blocked_submits == 0  # the off switch clears the streak, not defers it


def test_gate_suggested_command_always_clears_the_gate(workspace: Path) -> None:
    """The command the gate itself suggests must satisfy the gate.

    This is the anti-false-block invariant: narrowing evidence can never leave
    the gate asking for a check it would then reject.
    """
    from kite.application.verification import next_required_check_command

    ws = workspace
    for path in ("src/app.py", "app.py"):
        vc = _edited(ws, path)
        cmd = next_required_check_command(vc)
        assert cmd, f"no suggested command for {path}"
        vc.on_tool_end("bash", {"command": cmd}, {"ok": True, "returncode": 0, "output": "1 passed"})
        assert vc.submit_block_reason(REPORT) is None, f"false block on suggested {cmd!r}"


def test_whole_package_and_directory_scoped_checks_still_count(workspace: Path) -> None:
    """Only a *specific unrelated file* is disqualifying evidence.

    `pytest -q`, `pytest -q tests/` and `pytest -q src/app.py` all exercise the
    edit and must keep passing — narrowing must not become a new false blocker.
    """
    ws = workspace
    for cmd in ("pytest -q", "python -m pytest -q", "pytest -q tests/", "pytest tests/ -q"):
        vc = _edited(ws)
        vc.begin_turn()
        vc.on_tool_end("bash", {"command": cmd}, {"ok": True, "returncode": 0, "output": "1 passed"})
        assert vc.submit_block_reason(REPORT) is None, f"false block on {cmd!r}"


def test_shell_composed_command_keeps_full_scope(workspace: Path) -> None:
    """A `cd pkg && pytest …` command is not a plain argument list.

    The planner itself emits that shape, so its scope is left alone rather than
    read off a base directory that has already moved.
    """
    ws = workspace
    vc = _edited(ws)
    vc.begin_turn()
    vc.on_tool_end(
        "bash",
        {"command": "cd src && pytest -q tests/test_app.py"},
        {"ok": True, "returncode": 0, "output": "1 passed"},
    )
    assert vc.submit_block_reason(REPORT) is None


def test_read_only_turn_needs_no_evidence(workspace: Path) -> None:
    """Q&A with no edits submits freely — only false "tests pass" claims block."""
    ws = workspace
    vc = VerificationCollector(workspace_root=str(ws))
    assert vc.submit_block_reason("Here is the answer you asked for.") is None
    assert vc.submit_block_reason("All tests pass, I verified it.") is not None


def test_run_result_surfaces_the_gate_reason() -> None:
    """A blocked-then-stalled run carries its reason onto RunResult.

    `_build_run_result` reads the legacy dict; without `blocked_reason` in the
    loop's result the reason is silently dropped and an orchestrator sees a run
    that just... ended.
    """
    from kite.application.service import _build_run_result

    result = _build_run_result(
        "blocked",
        None,
        "run-1",
        {"exit_status": "Stalled", "blocked_reason": "Submit blocked: incomplete verification"},
    )
    assert result.blocked_reason == "Submit blocked: incomplete verification"
    assert result.approval_reason == ""  # a gate block is not an approval denial
