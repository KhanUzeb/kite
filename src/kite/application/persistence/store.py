"""SQLite canonical event store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kite.application.events import EventEnvelope, EventSink
from kite.application.persistence.migrations import MIGRATIONS, SCHEMA_VERSION
from kite.application.persistence.redaction import redact_payload


class SQLiteEventStore(EventSink):
    """Transactional event store with WAL and busy timeout."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._migrate()

    def _migrate(self) -> None:
        for sql in MIGRATIONS:
            self._conn.execute(sql)
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
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
                    envelope.event_id,
                    envelope.run_id,
                    envelope.parent_event_id,
                    envelope.sequence,
                    envelope.timestamp,
                    envelope.kind,
                    json.dumps(payload),
                    envelope.schema_version,
                    envelope.redaction_version,
                ),
            )
            now = datetime.now(UTC).isoformat()
            self._conn.execute("UPDATE runs SET updated_at=? WHERE run_id=?", (now, envelope.run_id))
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def load_run(self, run_id: str) -> list[EventEnvelope]:
        rows = self._conn.execute(
            """
            SELECT event_id, run_id, parent_event_id, sequence, timestamp, kind,
                   payload_json, schema_version, redaction_version
            FROM events WHERE run_id=? ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        out: list[EventEnvelope] = []
        for row in rows:
            out.append(
                EventEnvelope(
                    event_id=row[0],
                    run_id=row[1],
                    parent_event_id=row[2],
                    sequence=row[3],
                    timestamp=row[4],
                    kind=row[5],  # type: ignore[arg-type]
                    payload=json.loads(row[6]),
                    schema_version=row[7],
                    redaction_version=row[8],
                ),
            )
        return out

    def save_context_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> str:
        snap_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO context_snapshots(snapshot_id, run_id, prompt_hash, assembler_version, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snap_id,
                run_id,
                snapshot.get("prompt_hash", ""),
                snapshot.get("assembler_version", ""),
                json.dumps(redact_payload(snapshot)),
                now,
            ),
        )
        return snap_id

    def delete_run(self, run_id: str) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute("DELETE FROM events WHERE run_id=?", (run_id,))
            self._conn.execute("DELETE FROM context_snapshots WHERE run_id=?", (run_id,))
            self._conn.execute("DELETE FROM budgets WHERE run_id=?", (run_id,))
            self._conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._conn.close()
