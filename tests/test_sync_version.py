"""Version stamp sync script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_scripts_have_release_marker() -> None:
    import re
    import tomllib

    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    marker = re.compile(r"^# kite-release-version: ([\d.]+)$", re.MULTILINE)
    scripts = ROOT / "scripts"
    for path in sorted(scripts.iterdir()):
        if path.suffix not in {".sh", ".ps1", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        match = marker.search(text)
        assert match, f"{path.name} missing release marker"
        assert match.group(1) == expected, f"{path.name} marker {match.group(1)} != {expected}"


def test_sync_version_check_passes_on_repo() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_sync_version_sync_is_idempotent() -> None:
    before = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    after = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert before == after
    assert "already at" in proc.stdout or "updated" in proc.stdout
