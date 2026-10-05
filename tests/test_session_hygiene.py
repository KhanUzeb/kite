"""Session hygiene — deletion reaps sidecars, and listing stays bounded."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from kite.memory.session import (
    create_session,
    delete_all_sessions,
    delete_session,
    list_sessions,
    prune_sessions,
    sessions_dir,
)
from kite.memory.session_analytics import SessionStats, load_session_stats, save_session_stats


def _session(task: str = "demo", cwd: str = "/tmp") -> str:
    s = create_session(task=task, cwd=cwd, provider="p", model="m")
    s.append({"role": "user", "content": task})
    return s.id


def _leftovers(session_id: str) -> list[str]:
    return sorted(p.name for p in sessions_dir().iterdir() if session_id in p.name)


def _write_sidecar(session_id: str, updated_at: float, mtime: float) -> Path:
    """Stamp the sidecar so updated_at and its file mtime agree."""
    side = sessions_dir() / f"{session_id}.meta"
    side.write_text(json.dumps({"updated_at": updated_at}) + "\n", encoding="utf-8")
    os.utime(side, (mtime, mtime))
    return side


def test_delete_session_reaps_every_sidecar_and_reports_honestly(kite_home: Path) -> None:
    """Deleting a session must leave nothing named after it — stats sidecar included."""
    target = _session("with stats")
    other = _session("bystander")
    stats_path = save_session_stats(SessionStats(session_id=target, created_at=1.0, updated_at=2.0))
    assert stats_path.is_file() and load_session_stats(target) is not None

    gone = delete_session(target)
    assert (gone.id, gone.session, gone.trajectory) == (target, True, False)
    assert _leftovers(target) == []
    # Bystander survives intact, sidecars and all.
    assert load_session_stats(other) is None
    assert sorted(_leftovers(other)) == [f"{other}.jsonl", f"{other}.meta"]


def test_delete_all_reaps_live_and_orphaned_sidecars(kite_home: Path) -> None:
    """delete_all must also collect sidecars whose transcript is already gone."""
    live = [_session(f"live-{i}") for i in range(3)]
    for sid in live:
        save_session_stats(SessionStats(session_id=sid, created_at=1.0, updated_at=2.0))
    # Orphan left behind by a pre-fix delete or a crash between unlinks.
    orphan = _session("orphan")
    orphan_stats = save_session_stats(SessionStats(session_id=orphan, created_at=1.0, updated_at=2.0))
    (sessions_dir() / f"{orphan}.jsonl").unlink()
    (sessions_dir() / f"{orphan}.meta").unlink()
    assert orphan_stats.is_file()

    deleted = delete_all_sessions()
    assert sorted(d.id for d in deleted) == sorted(live)
    assert _leftovers(orphan) == [] and _leftovers(live[0]) == []
    assert list(sessions_dir().iterdir()) == []


def test_list_sessions_orders_by_updated_at_when_sidecar_is_newer_than_jsonl(kite_home: Path) -> None:
    """The mtime prefilter trusts the sidecar, so updated_at ordering survives.

    Transcript mtimes are deliberately in the *opposite* order from updated_at:
    ranking on jsonl mtime alone would return the wrong sessions.
    """
    ids = [_session(f"task-{i}") for i in range(6)]
    ladder = {sid: 1_000.0 + 100 * i for i, sid in enumerate(ids)}
    base = time.time() - 10_000
    for sid in ids:
        updated = ladder[sid]
        _write_sidecar(sid, updated, mtime=base + updated)
        # Transcript mtime reversed against updated_at.
        os.utime(sessions_dir() / f"{sid}.jsonl", (base - updated, base - updated))

    newest_first = [sid for sid, _ in sorted(ladder.items(), key=lambda kv: kv[1], reverse=True)]
    assert [m.id for m in list_sessions(limit=3)] == newest_first[:3]
    # updated_at (not created_at) decides — created_at is still ascending here.
    assert [m.updated_at for m in list_sessions(limit=2)] == [ladder[sid] for sid in newest_first[:2]]
    assert [m.id for m in list_sessions(query="task-1", limit=5)] == [ids[1]]


def test_list_sessions_bounds_meta_parses_without_dropping_newest(kite_home: Path, monkeypatch) -> None:
    """A small limit must not pay full-file-count meta parsing, nor lose rows."""
    ids = [_session(f"bulk-{i}") for i in range(120)]
    ladder = {sid: 10_000.0 + i for i, sid in enumerate(ids)}
    base = time.time() - 10_000
    for sid, updated in ladder.items():
        _write_sidecar(sid, updated, mtime=base + updated)

    from kite.memory import session as session_mod

    calls: list[Path] = []
    original = session_mod._read_session_meta

    def counting(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(session_mod, "_read_session_meta", counting)
    rows = list_sessions(limit=5)

    expected = [sid for sid, _ in sorted(ladder.items(), key=lambda kv: kv[1], reverse=True)][:5]
    assert [m.id for m in rows] == expected
    assert len(calls) < len(ids) / 2  # bounded, not one parse per file
    assert set(expected) <= {p.stem for p in calls}  # nothing in the newest N was skipped

    # prune_sessions leans on list_sessions(limit=10_000) — still exact.
    assert prune_sessions(120) == []
    removed = prune_sessions(2)
    removed_ids = [d.id for d in removed]
    assert len(removed_ids) == len(ids) - 2
    assert set(removed_ids) == set(ids[:-2])
    assert removed_ids == list(reversed(ids[:-2]))  # newest-first among the removed
    assert [m.id for m in list_sessions(limit=2)] == [ids[-1], ids[-2]]
    with pytest.raises(FileNotFoundError):
        delete_session("no-such-session-0000")