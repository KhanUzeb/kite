"""Smoke test for scripts/verify_release_pr.sh."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_release_pr.sh"


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
