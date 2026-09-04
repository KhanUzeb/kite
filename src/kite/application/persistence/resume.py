"""Resume state reconstruction from persisted events."""

from __future__ import annotations

import json
from typing import Any

from kite.application.persistence.store import SQLiteEventStore


def build_resume_state(store: SQLiteEventStore, run_id: str) -> dict[str, Any]:
    """Reconstruct resume payload from canonical store."""
    events = store.load_run(run_id)
    row = store._conn.execute(
        "SELECT task, workspace, config_json, policy_version FROM runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if not row:
        return {}
    config = json.loads(row[2] or "{}")
    last_kinds = [e.kind for e in events[-5:]]
    return {
        "run_id": run_id,
        "task": row[0],
        "workspace": row[1],
        "effective_config": config,
        "policy_version": row[3],
        "event_count": len(events),
        "last_event_kinds": last_kinds,
        "resumable": len(events) > 0,
    }
