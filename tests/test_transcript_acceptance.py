"""Transcript acceptance — deterministic replay of canonical events."""

from __future__ import annotations

from kite.application.events import EventSequencer
from kite.application.ui import ReplEventReducer
from kite.eval import ReplayBundle, run_replay


def test_reducer_tracks_verification_and_submit_blocked() -> None:
    reducer = ReplEventReducer()
    seq = EventSequencer("accept-1")
    reducer.apply(seq.emit("agent_start", {"task": "edit html"}))
    reducer.apply(seq.emit("verification_plan", {"artifact_kinds": ["html"], "required_checks": 1}))
    reducer.apply(seq.emit("verification_record", {"ok": True, "artifact_kind": "html"}))
    reducer.apply(seq.emit("submit_blocked", {"reason": "claims without evidence"}))
    snap = reducer.snapshot()
    assert snap["status"] == "blocked"


def test_reducer_approval_request_decision_cycle() -> None:
    reducer = ReplEventReducer()
    seq = EventSequencer("accept-2")
    reducer.apply(seq.emit("approval_request", {"request_id": "a1", "tool": "bash"}))
    assert reducer.snapshot()["status"] == "awaiting_approval"
    reducer.apply(seq.emit("approval_decision", {"request_id": "a1", "decision": "allow"}))
    assert reducer.snapshot()["status"] == "running"


def test_replay_bundle_no_live_provider() -> None:
    bundle = ReplayBundle(
        run_id="transcript-1",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "Done — html updated."}],
    )
    out = run_replay(bundle)
    assert out["ok"]
    assert "Done" in out["content"]
    assert "pytest" not in out["content"].lower()
