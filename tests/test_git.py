"""Git checkpoints do not commit unless asked."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kite.ui.git import GitCheckpoints


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "kite@test"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "kite"], cwd=root, check=True, capture_output=True)
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)


def test_flush_does_not_commit_by_default(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    git = GitCheckpoints.open(tmp_path)
    git.record(str(tmp_path / "a.txt"), "edit a")
    assert git.flush() is None
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "kite:" not in (log.stdout or "")


def test_explicit_commit_still_works(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    git = GitCheckpoints.open(tmp_path)
    sha = git.commit([str(tmp_path / "a.txt")], "asked")
    assert sha
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (log.stdout or "").startswith("kite:")
