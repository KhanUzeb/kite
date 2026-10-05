"""Crash-tolerance and duplicate-accounting hygiene in the session analytics layer.

Each test here corresponds to a defect that reproduced as a crash, a wrong
number, or a divergence risk. Tests use the shared ``kite_home`` fixture so
every session/trajectory path is isolated from the real ~/.kite.
"""

from __future__ import annotations

import json

from kite.memory import session, session_analytics
from kite.memory.session import create_session
from kite.memory.session_analytics import (
    list_session_events,
    scan_session_file,
)


def _crashed_session(kite_home, tmp_path, *, payloads: int = 2):
    """Session with durable events, returned with its on-disk path."""
    s = create_session(task="crash", cwd=str(tmp_path), provider="p", model="m")
    for i in range(payloads):
        s.append({"role": "user", "content": f"message {i}"})
        s.record_event("tool_end", {"tool": "read", "ok": True})
    return s, s._session_path()


def test_scan_survives_non_object_jsonl_rows(kite_home, tmp_path) -> None:
    """A crash can leave a valid-JSON-but-not-an-object line; the scanner must not blow up.

    Unhandled, ``row.get(...)`` on a list/scalar raised AttributeError straight
    out of scan_session_file, so ``kite dashboard`` crashed on a corrupt session
    instead of reporting the rows that survived. Non-dict rows are skipped, the
    same way session.py's own loader skips them.
    """
    _, path = _crashed_session(kite_home, tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write("[1, 2, 3]\n")
        f.write("42\n")
        f.write('"a bare string"\n')

    stats = scan_session_file(path)

    assert stats is not None
    # Everything written before the corruption is still counted.
    assert stats.message_count == 2
    assert stats.tool_calls == 2


def test_scan_and_events_survive_undecodable_bytes(kite_home, tmp_path) -> None:
    """A half-flushed write can leave invalid utf-8 mid-file — that is not a crash.

    UnicodeDecodeError is not an OSError, so the existing ``except (OSError,
    json.JSONDecodeError)`` never caught it and both readers propagated it out.
    A torn transcript is the normal post-crash state; it must degrade to the
    rows that did decode.
    """
    _, path = _crashed_session(kite_home, tmp_path)
    with path.open("ab") as f:
        f.write(b"\xff\xfe truncated \x00 binary sector\n")
        f.write(b'{"type": "message", "mess')

    stats = scan_session_file(path)
    events = list_session_events(path)

    assert stats is not None
    assert stats.message_count == 2
    assert stats.tool_calls == 2
    # The undecodable tail must not hide the intact events before it.
    assert [e["kind"] for e in events] == ["tool_end", "tool_end"]


def test_checkpoint_counted_once_per_saved_checkpoint(kite_home, tmp_path) -> None:
    """One saved checkpoint must yield stats.checkpoints == 1, not 2.

    The production save path writes a ``context_checkpoint`` row *and* a
    ``checkpoint`` event for the same checkpoint id (loop.py's
    _maybe_phase_checkpoint). scan_session_file counted both, so the dashboard
    "checkpoints" row double-reported every checkpoint a long task took.
    """
    s, path = _crashed_session(kite_home, tmp_path, payloads=1)

    # Mirror loop.py exactly: record_context_checkpoint then _emit("checkpoint", ...).
    cp_id = "cp-phase-7"
    s.record_context_checkpoint(cp_id, label="phase turn 7", reason="auto")
    s.record_event(
        "checkpoint",
        {"id": cp_id, "label": "phase turn 7", "reason": "long_task_phase", "turn": 7},
    )

    kinds = [json.loads(line).get("kind") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert "context_checkpoint" in [
        json.loads(line).get("type")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert kinds.count("checkpoint") == 1  # the duplication is real in the file

    stats = scan_session_file(path)
    assert stats.checkpoints == 1


def test_trajectory_path_has_single_source_of_truth(kite_home) -> None:
    """_trajectory_path must not be copy-pasted between session.py and session_analytics.py.

    The two copies were byte-identical (same sha256) — a duplicate that silently
    diverges the moment either side is fixed, because nothing links them.
    session_analytics already imports from session, so it can share the canonical
    helper instead of owning a copy.
    """
    assert session_analytics._trajectory_path is session._trajectory_path
    # And the shared helper still resolves into the active (isolated) home.
    assert session_analytics._trajectory_path("abc").parent.name == "trajectories"