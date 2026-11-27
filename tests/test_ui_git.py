"""Behavioral coverage for the combined git status probe in ``kite.ui.git``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kite.ui import git as git_ui

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


@pytest.fixture(autouse=True)
def _isolated_git_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh probe cache and a ceiling so no repo above tmp_path leaks in."""
    monkeypatch.setattr(git_ui, "_probe_cache", {})
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=60,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-qm", "base")
    return path


def _current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def test_one_status_call_serves_repo_branch_and_dirty(tmp_path: Path, monkeypatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    calls: list[tuple[str, ...]] = []
    real_run = git_ui._run

    def recording(cwd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(tuple(str(part) for part in args))
        return real_run(cwd, *args, **kwargs)

    monkeypatch.setattr(git_ui, "_run", recording)

    assert git_ui.is_repo(repo) is True
    assert git_ui.git_branch(repo) == _current_branch(repo)
    assert git_ui.git_dirty_count(repo) == 2

    assert len(calls) == 1
    assert calls[0][:2] == ("git", "status")
    assert "--porcelain=v1" in calls[0]
    assert "--branch" in calls[0]

    # The single snapshot is reused by all three helpers while it is fresh.
    assert git_ui.is_repo(repo) is True
    assert git_ui.git_branch(repo) == _current_branch(repo)
    assert git_ui.git_dirty_count(repo) == 2
    assert len(calls) == 1


def test_non_repository_bare_repo_and_git_dir_all_degrade(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    assert git_ui.is_repo(outside) is False
    assert git_ui.git_branch(outside) == ""
    assert git_ui.git_dirty_count(outside) == -1

    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, timeout=60)
    assert git_ui.is_repo(bare) is False
    assert git_ui.git_branch(bare) == ""
    assert git_ui.git_dirty_count(bare) == -1

    repo = _init_repo(tmp_path / "repo")
    inside_git_dir = repo / ".git"
    assert git_ui.is_repo(inside_git_dir) is False
    assert git_ui.git_branch(inside_git_dir) == ""
    assert git_ui.git_dirty_count(inside_git_dir) == -1


def test_detached_head_keeps_head_sentinel(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "--detach", "HEAD")

    assert git_ui.is_repo(repo) is True
    assert git_ui.git_branch(repo) == "HEAD"
    assert git_ui.git_dirty_count(repo) == 0


def test_unborn_branch_reports_empty_branch_and_counts_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "first.txt").write_text("x\n", encoding="utf-8")

    # rev-parse --abbrev-ref HEAD failed on an unborn branch, so the old helper
    # returned ""; keep that rather than surfacing the configured branch name.
    assert git_ui.git_branch(repo) == ""
    assert git_ui.is_repo(repo) is True
    assert git_ui.git_dirty_count(repo) == 1


def test_upstream_and_ahead_header_parses_to_local_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    branch = _current_branch(repo)
    # A hand-written refs/remotes/origin/<branch> is only treated as a remote
    # tracking ref once the remote has url/fetch configured; git otherwise
    # emits a plain "## <branch>" header with no upstream section.
    _git(repo, "config", "remote.origin.url", "https://example.invalid/repo.git")
    _git(repo, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    _git(repo, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
    _git(repo, "config", f"branch.{branch}.remote", "origin")
    _git(repo, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")
    (repo / "tracked.txt").write_text("ahead\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "ahead")

    assert _git(repo, "status", "--porcelain=v1", "--branch").stdout.startswith(
        f"## {branch}...origin/{branch} [ahead 1]"
    )
    assert git_ui.git_branch(repo) == branch
    assert git_ui.git_dirty_count(repo) == 0


def test_dirty_count_matches_porcelain_entries(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "old.txt").write_text("old\n", encoding="utf-8")
    _git(repo, "add", "old.txt")
    _git(repo, "commit", "-qm", "old")
    _git(repo, "mv", "old.txt", "renamed.txt")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    status = _git(repo, "status", "--porcelain=v1", "--branch").stdout.splitlines()
    expected = sum(1 for line in status[1:] if line.strip())
    assert expected == 3
    assert git_ui.git_dirty_count(repo) == expected


def test_timeout_degrades_and_is_cached(tmp_path: Path, monkeypatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    calls: list[tuple[str, ...]] = []

    def timeout(cwd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(tuple(str(part) for part in args))
        raise subprocess.TimeoutExpired(cmd=["git", *args], timeout=10)

    monkeypatch.setattr(git_ui, "_run", timeout)

    assert git_ui.is_repo(repo) is False
    assert git_ui.git_branch(repo) == ""
    assert git_ui.git_dirty_count(repo) == -1
    assert len(calls) == 1

    # The failed snapshot is cached too, so a hung git is not retried per helper.
    assert git_ui.git_dirty_count(repo) == -1
    assert git_ui.is_repo(repo) is False
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["timeout", "failure"])
def test_slow_failed_probe_stamps_at_completion(tmp_path: Path, monkeypatch, mode: str) -> None:
    """A 10s probe must not hand back a sentinel that is already TTL-expired."""
    repo = _init_repo(tmp_path / "repo")
    calls: list[tuple[str, ...]] = []
    clock = [1000.0]

    def slow(cwd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(tuple(str(part) for part in args))
        clock[0] += float(kwargs.get("timeout", 10))  # burn the whole probe budget
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd=["git", *args], timeout=10)
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(git_ui, "_run", slow)
    monkeypatch.setattr(git_ui.time, "monotonic", lambda: clock[0])

    assert git_ui.git_dirty_count(repo) == -1
    assert len(calls) == 1
    assert git_ui._probe_cache[str(repo)].at == 1010.0

    # Within 4s of *completion*, every helper reuses the same sentinel.
    clock[0] = 1013.0
    assert git_ui.git_dirty_count(repo) == -1
    assert git_ui.git_branch(repo) == ""
    assert git_ui.is_repo(repo) is False
    assert len(calls) == 1

    # Only once the completion-based TTL really expires is a new probe made.
    clock[0] = 1014.1
    assert git_ui.git_dirty_count(repo) == -1
    assert len(calls) == 2


def test_ttl_windows_are_per_consumer(tmp_path: Path, monkeypatch) -> None:
    """One snapshot, but each helper keeps its own staleness window."""
    repo = _init_repo(tmp_path / "repo")
    branch = _current_branch(repo)
    calls: list[tuple[str, ...]] = []
    real_run = git_ui._run

    def recording(cwd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(tuple(str(part) for part in args))
        return real_run(cwd, *args, **kwargs)

    monkeypatch.setattr(git_ui, "_run", recording)
    now = 1000.0
    monkeypatch.setattr(git_ui.time, "monotonic", lambda: now)

    assert git_ui.is_repo(repo) is True
    assert len(calls) == 1

    # Past the 4s branch/dirty TTL but inside the 30s repo TTL: is_repo reuses
    # the snapshot while git_branch must refresh it with exactly one new probe.
    now = 1005.0
    assert git_ui.is_repo(repo) is True
    assert len(calls) == 1
    assert git_ui.git_branch(repo) == branch
    assert len(calls) == 2

    # The refreshed snapshot is now shared again by all three helpers.
    assert git_ui.git_dirty_count(repo) == 0
    assert git_ui.is_repo(repo) is True
    assert len(calls) == 2


def test_invalidation_refreshes_branch_and_dirty_snapshot(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    branch = _current_branch(repo)
    assert git_ui.git_branch(repo) == branch
    assert git_ui.git_dirty_count(repo) == 0

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    # Still inside the TTL: the snapshot is intentionally stale.
    assert git_ui.git_branch(repo) == branch
    assert git_ui.git_dirty_count(repo) == 0

    git_ui.invalidate_git_status_cache(repo)
    assert git_ui.git_branch(repo) == "feature"
    assert git_ui.git_dirty_count(repo) == 1
    assert git_ui.is_repo(repo) is True


def test_invalidate_all_clears_every_cached_repository(tmp_path: Path) -> None:
    first = _init_repo(tmp_path / "first")
    second = _init_repo(tmp_path / "second")
    assert git_ui.is_repo(first) is True
    assert git_ui.is_repo(second) is True
    assert len(git_ui._probe_cache) == 2

    git_ui.invalidate_git_status_cache()
    assert git_ui._probe_cache == {}
