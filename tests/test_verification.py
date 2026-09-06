"""Verification collector — artifact-aware evidence."""

from __future__ import annotations

import pytest

from kite.agent.verification import VerificationCollector
from kite.application.verification.collector_ops import html_parse_ok


@pytest.mark.parametrize(
    ("cmd", "ok", "rc", "expect_test", "expect_status"),
    [
        ("pytest tests/ -q", True, 0, True, "verified"),
        ("python -m pytest tests/ -q", True, 0, True, None),
        ("uv run pytest", False, 1, True, "failed"),
    ],
)
def test_bash_test_detection(cmd, ok, rc, expect_test, expect_status) -> None:
    vc = VerificationCollector()
    vc.on_tool_end("bash", {"command": cmd}, {"ok": ok, "returncode": rc, "output": "out"})
    assert any(a.kind == "test" for a in vc.artifacts) == expect_test
    if expect_status:
        assert vc.status() == expect_status


def test_idle_and_edits_need_verification() -> None:
    vc = VerificationCollector()
    assert vc.status() == "idle" and not vc.has_work()
    vc.on_tool_end("edit", {"path": "x.py"}, {"ok": True, "path": "x.py", "diff": "d"})
    assert vc.needs_tests()
    assert vc.post_edit_nudge() and "verification" in vc.post_edit_nudge().lower()


def test_html_edit_structural_not_pytest() -> None:
    html = "<html><body>ok</body></html>"
    vc = VerificationCollector()
    vc.on_tool_end(
        "write",
        {"path": "index.html", "content": html},
        {"ok": True, "path": "index.html", "diff": "d", "content": html},
    )
    assert not vc.needs_tests()
    nudge = vc.post_edit_nudge()
    assert nudge is None or "pytest" not in (nudge or "").lower()
    submission = "## Done\n- updated\n## Changed\n- `index.html`\n## Verification\n- ✓ html structural"
    assert vc.submit_block_reason(submission) is None
    assert html_parse_ok(html)


def test_malformed_html_fails_parse() -> None:
    assert not html_parse_ok("<html><body>no closing tags")


def test_next_required_check_command(workspace) -> None:
    from kite.application.verification.collector_ops import next_required_check_command

    vc = VerificationCollector(workspace_root=str(workspace))
    (workspace / "src").mkdir(exist_ok=True)
    (workspace / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / "tests").mkdir(exist_ok=True)
    (workspace / "tests" / "test_app.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    vc.on_tool_end("edit", {"path": "src/app.py"}, {"ok": True, "path": "src/app.py", "diff": "d"})
    cmd = next_required_check_command(vc)
    assert cmd
    assert "pytest" in cmd.lower() or "py_compile" in cmd.lower()

