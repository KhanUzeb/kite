"""Session listing/pruning cost must track rows requested, not store size.

The bug these lock down: ``list_sessions`` pre-ranked candidates by file mtime
and then parsed a ``limit + 32`` head, so ``list_sessions(limit=10)`` on a store
with hundreds of transcripts was *slower* than ``list_sessions(limit=10_000)`` —
an inversion that reads as a CLI hang with no output on the interactive paths
(``/sessions`` uses limit=30, ``kite sessions --delete-all`` uses limit=10_000).

Deliberately no wall-clock assertions: CI machines vary by an order of magnitude
and ms-bound tests flake. What is asserted instead is the *work* — how many
transcripts get their meta parsed — which is the thing that was actually
unbounded. The counting wrapper is copied from ``test_session_hygiene.py``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from kite.memory import session as session_mod
from kite.memory import session_analytics
from kite.memory.session import (
    create_session,
    delete_all_sessions,
    delete_session,
    list_sessions,
    prune_sessions,
    sessions_dir,
)

_BULK = 200


def _session(task: str = "demo", cwd: str = "/tmp") -> str:
    s = create_session(task=task, cwd=cwd, provider="p", model="m")
    s.append({"role": "user", "content": task})
    return s.id


def _write_sidecar(session_id: str, updated_at: float, mtime: float) -> Path:
    """Stamp the sidecar so updated_at and its file mtime agree."""
    side = sessions_dir() / f"{session_id}.meta"
    side.write_text(json.dumps({"updated_at": updated_at}) + "\n", encoding="utf-8")
    os.utime(side, (mtime, mtime))
    return side


def _bulk_ids(kite_home: Path, count: int = _BULK) -> list[str]:
    """``count`` sessions with strictly ascending updated_at, oldest first."""
    ids = [_session(f"bulk-{i}") for i in range(count)]
    base = time.time() - 100_000
    for i, sid in enumerate(ids):
        _write_sidecar(sid, base + i, mtime=base + i)
        os.utime(sessions_dir() / f"{sid}.jsonl", (base + i, base + i))
    return ids


def _count_meta_parses(monkeypatch: pytest.MonkeyPatch, call) -> tuple[list[Path], object]:
    """Run ``call`` with a counting wrapper around ``_read_session_meta``."""
    calls: list[Path] = []
    original = session_mod._read_session_meta

    def counting(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(session_mod, "_read_session_meta", counting)
    try:
        result = call()
    finally:
        monkeypatch.setattr(session_mod, "_read_session_meta", original)
    return calls, result


def _c_test_list_sessions_meta_parses_do_not_scale_with_store_size(kite_home: Path, monkeypatch) -> None:
    """A small limit must not pay for the whole store — the actual bug.

    Before: limit=10 parsed limit+32=42 heads on any store size, and the
    glob+``stat()`` pre-rank walked every transcript regardless of limit.
    """
    ids = _bulk_ids(kite_home)

    calls, rows = _count_meta_parses(monkeypatch, lambda: list_sessions(limit=10))

    assert [m.id for m in rows] == ids[-10:][::-1]
    # Bounded by the head, not the store: nowhere near one parse per transcript.
    assert len(calls) < _BULK / 4, f"{len(calls)} meta parses for {_BULK} sessions"
    # Nothing the caller asked for was skipped to hit the budget.
    assert {m.id for m in rows} <= {p.stem for p in calls}

    # The bound must not creep back toward the store size as the store grows.
    _bulk_ids(kite_home, count=40)
    small_calls, _ = _count_meta_parses(monkeypatch, lambda: list_sessions(limit=10))
    assert len(small_calls) <= len(calls) + 1, f"40-session store parsed more than {len(ids)}"


def _c_test_list_sessions_head_covers_unparseable_meta(kite_home: Path, monkeypatch) -> None:
    """The head slack must absorb sessions whose meta will not parse.

    Otherwise the cheap path silently returns fewer than ``limit`` rows just
    because the cutoff landed on a corrupt transcript.
    """
    ids = _bulk_ids(kite_home, count=60)
    # Corrupt the 4 newest transcripts so 56 clean ones sit below the cut.
    for sid in ids[-4:]:
        (sessions_dir() / f"{sid}.jsonl").write_text("not json at all\n", encoding="utf-8")

    calls, rows = _count_meta_parses(monkeypatch, lambda: list_sessions(limit=10))

    assert len(calls) <= 10 + session_mod._META_PARSE_SLACK
    # Still exactly 10 good rows even though the 4 newest are unreadable.
    assert len(rows) == 10
    assert rows[-1].id in set(ids[:-4])


def _c_test_list_sessions_ordering_includes_sidecar_newer_than_transcript(
    kite_home: Path, monkeypatch
) -> None:
    """Ranking must use max(transcript, sidecar) mtime, never transcript alone.

    ``note_runtime`` bumps ``updated_at`` through the sidecar without touching
    the transcript, so a transcript-mtime-only prefilter silently buries the
    session the user just used. This is the invariant the fast path must keep.
    """
    ids = [_session(f"task-{i}") for i in range(6)]
    ladder = {sid: 1_000.0 + 100 * i for i, sid in enumerate(ids)}
    base = time.time() - 10_000
    for sid in ids:
        updated = ladder[sid]
        _write_sidecar(sid, updated, mtime=base + updated)
        # Transcript mtimes deliberately reversed against updated_at.
        os.utime(sessions_dir() / f"{sid}.jsonl", (base - updated, base - updated))

    newest_first = [sid for sid, _ in sorted(ladder.items(), key=lambda kv: kv[1], reverse=True)]

    _calls, rows = _count_meta_parses(monkeypatch, lambda: list_sessions(limit=3))
    assert [m.id for m in rows] == newest_first[:3]
    assert [m.updated_at for m in rows] == [ladder[sid] for sid in newest_first[:3]]
    # The newest session's transcript is the *oldest* file on disk — proof the
    # sidecar carried the ordering, not the transcript.
    assert [m.id for m in list_sessions(limit=1)] == [newest_first[0]]

    # The query path still finds it, and still full-scans by design.
    assert [m.id for m in list_sessions(query="task-1", limit=5)] == [ids[1]]


def _c_test_prune_sessions_deletes_oldest_without_parsing_meta(kite_home: Path, monkeypatch) -> None:
    """prune needs ids and ages only — it must never open a transcript meta."""
    ids = _bulk_ids(kite_home, count=60)
    keep = 7

    assert prune_sessions(keep=len(ids)) == []

    calls, removed = _count_meta_parses(monkeypatch, lambda: prune_sessions(keep=keep, dry_run=False))
    removed_ids = [d.id for d in removed]

    assert calls == [], f"prune parsed meta for {[p.stem for p in calls]}"
    assert set(removed_ids) == set(ids[:-keep])
    assert removed_ids == list(reversed(ids[:-keep]))  # newest-first among the removed
    assert [m.id for m in list_sessions(limit=keep)] == ids[-keep:][::-1]
    assert not (sessions_dir() / f"{ids[0]}.jsonl").exists()


def _c_test_prune_sessions_ranks_by_sidecar_when_transcript_is_stale(
    kite_home: Path, monkeypatch
) -> None:
    """The newest session survives prune even when its transcript is oldest.

    Ranking prune on transcript mtime alone would delete the session the user
    just ran — the prune twin of the ordering invariant above.
    """
    ids = [_session(f"mix-{i}") for i in range(6)]
    ladder = {sid: 2_000.0 + 100 * i for i, sid in enumerate(ids)}
    base = time.time() - 20_000
    for sid in ids:
        _write_sidecar(sid, ladder[sid], mtime=base + ladder[sid])
        os.utime(sessions_dir() / f"{sid}.jsonl", (base - ladder[sid], base - ladder[sid]))

    calls, removed = _count_meta_parses(monkeypatch, lambda: prune_sessions(keep=2, dry_run=False))

    assert calls == []
    assert [d.id for d in removed] == list(reversed(ids[:4]))
    # glob order is filesystem order, so compare as a set.
    assert {p.stem for p in sessions_dir().glob("*.jsonl")} == set(ids[-2:])


def _c_test_delete_all_ignores_sidecar_only_and_stray_files(kite_home: Path) -> None:
    """A ``.meta`` with no transcript must not appear as a deleted session."""
    ids = [_session(f"live-{i}") for i in range(2)]
    (sessions_dir() / "ghost.meta").write_text('{"updated_at": 1.0}\n', encoding="utf-8")
    (sessions_dir() / "junk.jsonl.tmp").write_text("partial\n", encoding="utf-8")

    deleted = delete_all_sessions()

    assert sorted(d.id for d in deleted) == sorted(ids)
    # ghost.meta was an orphan for a session that never existed -> swept.
    assert not (sessions_dir() / "ghost.meta").exists()
    # The .tmp is not a sidecar: _reap_orphan_sidecars only takes .meta/.stats.json.
    assert (sessions_dir() / "junk.jsonl.tmp").exists()


def _c_test_ranked_transcripts_is_sidecar_aware_and_skips_orphans(kite_home: Path) -> None:
    """The shared ranking pass: max(transcript, sidecar), no meta, no orphans."""
    ids = _bulk_ids(kite_home, count=5)
    base = time.time() - 100_000
    # Sidecar for the oldest session is far newer than any transcript.
    os.utime(sessions_dir() / f"{ids[0]}.meta", (base + 9_000, base + 9_000))
    (sessions_dir() / "orphan.meta").write_text('{"updated_at": 1.0}\n', encoding="utf-8")

    ranked = session_mod._ranked_transcripts(sessions_dir())

    # ids[0] has the oldest transcript but by far the newest sidecar.
    assert sorted(ranked, key=ranked.__getitem__, reverse=True) == [ids[0]] + ids[:0:-1]
    assert ranked[ids[0]] > max(ranked[sid] for sid in ids[1:])
    assert "orphan" not in ranked
    assert all(isinstance(mtime, float) for mtime in ranked.values())


def _c_test_delete_session_still_enforces_id_containment(kite_home: Path) -> None:
    """Bulk paths skip the per-id resolve(), so the id guard must still hold."""
    target = _session("guarded")
    assert delete_session(target).id == target

    with pytest.raises(ValueError):
        session_analytics._stats_sidecar("../escape", resolved_root=session_mod.folder_root())
    with pytest.raises(ValueError):
        session_mod._trajectory_path("../escape", resolved_root=session_mod._trajectory_root())
    # The pre-resolved fast path returns the same file the slow path does.
    assert session_analytics._stats_sidecar(
        "abc", resolved_root=session_mod.folder_root()
    ) == session_analytics._stats_sidecar("abc")
    assert session_mod._trajectory_path(
        "abc", resolved_root=session_mod._trajectory_root()
    ) == session_mod._trajectory_path("abc")


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): list_sessions bounds + prune without meta parses."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k0_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_list_sessions_meta_parses_do_not_scale_with_store_size(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_list_sessions_head_covers_unparseable_meta(kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_list_sessions_ordering_includes_sidecar_newer_than_transcript(
            kite_home=_k2, monkeypatch=_mp2
        )
    finally:
        _mp2.undo()
    _mp3 = pytest.MonkeyPatch()
    try:
        _k3 = tmp_path / "k0_3"
        _k3.mkdir(parents=True, exist_ok=True)
        _mp3.setenv("KITE_HOME", str(_k3))
        _c_test_prune_sessions_deletes_oldest_without_parsing_meta(kite_home=_k3, monkeypatch=_mp3)
    finally:
        _mp3.undo()
    _mp4 = pytest.MonkeyPatch()
    try:
        _k4 = tmp_path / "k0_4"
        _k4.mkdir(parents=True, exist_ok=True)
        _mp4.setenv("KITE_HOME", str(_k4))
        _c_test_prune_sessions_ranks_by_sidecar_when_transcript_is_stale(
            kite_home=_k4, monkeypatch=_mp4
        )
    finally:
        _mp4.undo()


def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_delete_all_ignores_sidecar_only_and_stray_files, test_ranked_transcripts_is_sidecar_aware_and_skips_orphans, test_delete_session_still_enforces_id_containment."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k1_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_delete_all_ignores_sidecar_only_and_stray_files(kite_home=_k0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k1_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_ranked_transcripts_is_sidecar_aware_and_skips_orphans(kite_home=_k1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k1_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_delete_session_still_enforces_id_containment(kite_home=_k2)
    finally:
        _mp2.undo()