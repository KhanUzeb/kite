"""SQLite event store, schema, redaction, and resume reconstruction."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kite.application.events import EventEnvelope, EventSink, redact_payload

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, parent_run_id TEXT, status TEXT NOT NULL,
    task TEXT, workspace TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    config_json TEXT, policy_version TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_event_id TEXT,
    sequence INTEGER NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL,
    payload_json TEXT NOT NULL, schema_version INTEGER NOT NULL,
    redaction_version INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, sequence);
CREATE TABLE IF NOT EXISTS context_snapshots (
    snapshot_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, prompt_hash TEXT NOT NULL,
    assembler_version TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS budgets (
    run_id TEXT PRIMARY KEY, ledger_json TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""


class SQLiteEventStore(EventSink):
    """Transactional event store with WAL and busy timeout."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(_SCHEMA)
        if self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone() is None:
            self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))

    def ensure_run(self, run_id: str, *, task: str = "", workspace: str = "", config: dict | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO runs(run_id, status, task, workspace, created_at, updated_at, config_json, policy_version)
            VALUES (?, 'created', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (run_id, task, workspace, now, now, json.dumps(config or {}), "0.9.0"),
        )

    def append(self, envelope: EventEnvelope) -> None:
        payload = redact_payload(envelope.payload)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self.ensure_run(envelope.run_id)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO events(
                        event_id, run_id, parent_event_id, sequence, timestamp, kind,
                        payload_json, schema_version, redaction_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.event_id, envelope.run_id, envelope.parent_event_id,
                        envelope.sequence, envelope.timestamp, envelope.kind,
                        json.dumps(payload), envelope.schema_version, envelope.redaction_version,
                    ),
                )
                now = datetime.now(UTC).isoformat()
                self._conn.execute("UPDATE runs SET updated_at=? WHERE run_id=?", (now, envelope.run_id))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def load_run(self, run_id: str) -> list[EventEnvelope]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, run_id, parent_event_id, sequence, timestamp, kind,
                       payload_json, schema_version, redaction_version
                FROM events WHERE run_id=? ORDER BY sequence
                """,
                (run_id,),
            ).fetchall()
        return [
            EventEnvelope(
                event_id=row[0], run_id=row[1], parent_event_id=row[2], sequence=row[3],
                timestamp=row[4], kind=row[5], payload=json.loads(row[6]),
                schema_version=row[7], redaction_version=row[8],
            )
            for row in rows
        ]

    def save_context_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> str:
        snap_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO context_snapshots(snapshot_id, run_id, prompt_hash, assembler_version, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snap_id, run_id, snapshot.get("prompt_hash", ""), snapshot.get("assembler_version", ""),
                json.dumps(redact_payload(snapshot)), datetime.now(UTC).isoformat(),
            ),
        )
        return snap_id

    def delete_run(self, run_id: str) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for table in ("events", "context_snapshots", "budgets", "runs"):
                self._conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._conn.close()


def build_resume_state(store: SQLiteEventStore, run_id: str) -> dict[str, Any]:
    events = store.load_run(run_id)
    row = store._conn.execute(
        "SELECT task, workspace, config_json, policy_version FROM runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if not row:
        return {}
    return {
        "run_id": run_id,
        "task": row[0],
        "workspace": row[1],
        "effective_config": json.loads(row[2] or "{}"),
        "policy_version": row[3],
        "event_count": len(events),
        "last_event_kinds": [e.kind for e in events[-5:]],
        "resumable": bool(events),
    }
