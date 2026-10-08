"""Destructive session pruning must be opt-in.

`prune_sessions` unlinks transcripts with no trash and no backup, so a caller
that invokes it to *inspect* what it would remove must not be able to delete a
user's real history. A profiling harness once did exactly that and cost the
repo's owner 29 sessions, so the default is now a dry run.
"""

from __future__ import annotations

from pathlib import Path

from kite.memory import session as S


def _make(tmp_path: Path, n: int) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        s = S.create_session(task=f"task-{i}", cwd=str(tmp_path), provider="p", model="m")
        s.note_runtime(provider="p", model="m")
        ids.append(s.id)
    return ids


def test_prune_defaults_to_dry_run_matching_confirmed_deletion(kite_home, tmp_path) -> None:
    """The preview must preserve every file and match opt-in deletion exactly."""
    ids = _make(tmp_path, 6)
    folder = S.sessions_dir()

    victims = S.prune_sessions(keep=2)

    assert len(victims) == 4, [v.id for v in victims]
    # The whole point: every transcript is still on disk after the "prune".
    survivors = sorted(p.stem for p in folder.glob("*.jsonl"))
    assert survivors == sorted(ids), survivors

    # opt in explicitly, as the confirmed CLI and REPL callers do
    removed = S.prune_sessions(keep=2, dry_run=False)
    assert [r.id for r in removed] == [v.id for v in victims]
    assert {p.stem for p in folder.glob("*.jsonl")} == set(ids) - {v.id for v in victims}


def test_keep_covers_everything_is_a_no_op_in_either_mode(kite_home, tmp_path) -> None:
    _make(tmp_path, 3)
    assert S.prune_sessions(keep=10) == []
    assert S.prune_sessions(keep=10, dry_run=False) == []
    assert len(list(S.sessions_dir().glob("*.jsonl"))) == 3
