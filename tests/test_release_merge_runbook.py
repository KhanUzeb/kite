"""Handoff artifacts for merging release PR #18 (v0.7.1)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "agent-pr-merge-runbook.md"
VERIFY = ROOT / "scripts" / "verify_release_pr.sh"


def test_merge_runbook_exists_and_targets_pr_18() -> None:
    assert RUNBOOK.is_file()
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "PR #18" in text
    assert "cursor/release-0.7.1-8708" in text
    assert "Do not merge" in text and "#7" in text
    assert "verify_release_pr.sh" in text


@pytest.mark.skipif(sys.platform == "win32", reason="verify_release_pr.sh requires bash")
def test_verify_release_script_help() -> None:
    assert VERIFY.is_file()
    proc = subprocess.run(
        [str(VERIFY), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "usage:" in proc.stdout
