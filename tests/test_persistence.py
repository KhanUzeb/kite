"""SQLite persistence and resume tests."""

from __future__ import annotations

from pathlib import Path

from kite.application.events import EventSequencer
from kite.application.persistence import SQLiteEventStore, build_resume_state, redact_payload


def test_sqlite_event_store_append_and_load(tmp_path: Path) -> None:
    db = tmp_path / "kite.db"
    store = SQLiteEventStore(db)
    seq = EventSequencer("run-1")
    e1 = seq.emit("agent_start", {"task": "t"})
    e2 = seq.emit("agent_end", {"api_key": "sk-secret12345678901234567890"})
    store.append(e1)
    store.append(e2)
    loaded = store.load_run("run-1")
    assert len(loaded) == 2
    assert loaded[1].sequence == 2
    assert "[REDACTED]" in str(loaded[1].payload)
    store.close()


def test_delete_run_cascades(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "k.db")
    seq = EventSequencer("run-del")
    store.append(seq.emit("turn_start", {}))
    store.delete_run("run-del")
    assert store.load_run("run-del") == []
    store.close()


def test_resume_state(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "r.db")
    store.ensure_run("run-r", task="fix bug", workspace="/proj", config={"model": "gpt-4"})
    seq = EventSequencer("run-r")
    store.append(seq.emit("turn_start", {"n": 1}))
    state = build_resume_state(store, "run-r")
    assert state["resumable"]
    assert state["task"] == "fix bug"
    assert state["effective_config"]["model"] == "gpt-4"
    store.close()


def test_redact_payload() -> None:
    out = redact_payload({"token": "Bearer abc.def.ghi"})
    assert "[REDACTED]" in str(out)
