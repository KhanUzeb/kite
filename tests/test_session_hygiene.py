"""Session deletion reaps sidecars without touching unrelated files."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.memory.session import (
    create_session,
    delete_all_sessions,
    delete_session,
    sessions_dir,
)
from kite.memory.session_analytics import SessionStats, load_session_stats, save_session_stats


def _session(task: str = "demo", cwd: str = "/tmp") -> str:
    s = create_session(task=task, cwd=cwd, provider="p", model="m")
    s.append({"role": "user", "content": task})
    return s.id


def _leftovers(session_id: str) -> list[str]:
    return sorted(p.name for p in sessions_dir().iterdir() if session_id in p.name)


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
    with pytest.raises(FileNotFoundError):
        delete_session("no-such-session-0000")


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
    (sessions_dir() / "ghost.meta").write_text('{"updated_at": 1.0}\n', encoding="utf-8")
    stray = sessions_dir() / "junk.jsonl.tmp"
    stray.write_text("partial\n", encoding="utf-8")

    deleted = delete_all_sessions()
    assert sorted(d.id for d in deleted) == sorted(live)
    assert _leftovers(orphan) == [] and _leftovers(live[0]) == []
    assert list(sessions_dir().iterdir()) == [stray]
    assert stray.read_text(encoding="utf-8") == "partial\n"