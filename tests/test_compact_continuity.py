"""Continuity episode recorded after compaction helper."""

from __future__ import annotations

from kite.memory.continuity import latest_continuity_markdown, record_continuity_after_compact
from kite.memory.store import MemoryStore


def test_record_continuity_after_compact(workspace, kite_home) -> None:
    store = MemoryStore.open(workspace)
    md = record_continuity_after_compact(
        store=store,
        messages=[
            {"role": "user", "content": "Ship the fix"},
            {"role": "assistant", "content": "Patched src/app.py"},
        ],
        todos=[{"status": "in_progress", "content": "add regression test"}],
        session_id="sess1",
        cwd=str(workspace),
        task="Ship the fix",
    )
    assert "## Continuity" in md
    loaded = latest_continuity_markdown(store, session_id="sess1")
    assert "Ship the fix" in loaded
