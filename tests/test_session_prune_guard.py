"""Destructive session pruning must be opt-in.

`prune_sessions` unlinks transcripts with no trash and no backup, so a caller
that invokes it to *inspect* what it would remove must not be able to delete a
user's real history. A profiling harness once did exactly that and cost the
repo's owner 29 sessions, so the default is now a dry run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.memory import session as S
from kite.memory.session import DeletedSession


def _make(kite_home: Path, tmp_path: Path, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        s = S.create_session(task=f"task-{i}", cwd=str(tmp_path), provider="p", model="m")
        s.note_runtime(provider="p", model="m")
        ids.append(s.id)
    return ids


def _c_test_prune_defaults_to_a_dry_run(kite_home, tmp_path) -> None:
    """A bare prune_sessions() call reports victims and deletes nothing."""
    ids = _make(kite_home, tmp_path, 6)
    folder = S.sessions_dir()

    victims = S.prune_sessions(keep=2)

    assert len(victims) == 4, [v.id for v in victims]
    assert all(isinstance(v, DeletedSession) for v in victims)
    # The whole point: every transcript is still on disk after the "prune".
    survivors = sorted(p.stem for p in folder.glob("*.jsonl"))
    assert survivors == sorted(ids), survivors


def _c_test_dry_run_reports_the_same_victims_as_a_real_prune(kite_home, tmp_path) -> None:
    """A dry run is a faithful preview, so the count shown is the count deleted."""
    _make(kite_home, tmp_path, 6)

    preview = S.prune_sessions(keep=2)
    assert len(preview) == 4

    # opt in explicitly, as the confirmed CLI and REPL callers do
    removed = S.prune_sessions(keep=2, dry_run=False)
    assert [r.id for r in removed] == [p.id for p in preview]
    assert len(list(S.sessions_dir().glob("*.jsonl"))) == 2


def _c_test_keep_covers_everything_is_a_no_op_in_either_mode(kite_home, tmp_path) -> None:
    _make(kite_home, tmp_path, 3)
    assert S.prune_sessions(keep=10) == []
    assert S.prune_sessions(keep=10, dry_run=False) == []
    assert len(list(S.sessions_dir().glob("*.jsonl"))) == 3


def _c_test_confirmed_caller_can_still_prune_for_real(kite_home, tmp_path) -> None:
    """The guard must not turn pruning into a no-op nobody can perform."""
    _make(kite_home, tmp_path, 5)
    removed = S.prune_sessions(keep=1, dry_run=False)
    assert len(removed) == 4
    assert len(list(S.sessions_dir().glob("*.jsonl"))) == 1


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_prune_defaults_to_a_dry_run, test_dry_run_reports_the_same_victims_as_a_real_prune, test_keep_covers_everything_is_a_no_op_in_either_mode, test_confirmed_caller_can_still_prune_for_real."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k0_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _t0 = tmp_path / "t0_0"
        _t0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_prune_defaults_to_a_dry_run(kite_home=_k0, tmp_path=_t0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _t1 = tmp_path / "t0_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_dry_run_reports_the_same_victims_as_a_real_prune(kite_home=_k1, tmp_path=_t1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _t2 = tmp_path / "t0_2"
        _t2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_keep_covers_everything_is_a_no_op_in_either_mode(kite_home=_k2, tmp_path=_t2)
    finally:
        _mp2.undo()
    _mp3 = pytest.MonkeyPatch()
    try:
        _k3 = tmp_path / "k0_3"
        _k3.mkdir(parents=True, exist_ok=True)
        _t3 = tmp_path / "t0_3"
        _t3.mkdir(parents=True, exist_ok=True)
        _mp3.setenv("KITE_HOME", str(_k3))
        _c_test_confirmed_caller_can_still_prune_for_real(kite_home=_k3, tmp_path=_t3)
    finally:
        _mp3.undo()
