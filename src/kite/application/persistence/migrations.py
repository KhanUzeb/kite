"""SQLite schema migrations."""

from __future__ import annotations

SCHEMA_VERSION = 1

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        parent_run_id TEXT,
        status TEXT NOT NULL,
        task TEXT,
        workspace TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        config_json TEXT,
        policy_version TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        parent_event_id TEXT,
        sequence INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        redaction_version INTEGER NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, sequence);
    """,
    """
    CREATE TABLE IF NOT EXISTS context_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        assembler_version TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS budgets (
        run_id TEXT PRIMARY KEY,
        ledger_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    """,
)
