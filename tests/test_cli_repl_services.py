"""CLI result and REPL reducer tests."""

from __future__ import annotations

import json

from kite.application.cli import CliResult, ExitCode
from kite.application.contracts import RunResult
from kite.application.events import EventSequencer
from kite.application.ui import ReplEventReducer


def test_cli_result_exit_codes() -> None:
    ok = CliResult.from_run_result(RunResult(status="completed", stop_reason="submitted", final_message="done"))
    assert ok.exit_code == ExitCode.SUCCESS
    cancelled = CliResult.from_run_result(RunResult(status="cancelled", stop_reason="cancelled"))
    assert cancelled.exit_code == ExitCode.CANCELLED
    payload = json.loads(ok.to_json())
    assert payload["ok"] is True


def test_repl_reducer_projects_events() -> None:
    reducer = ReplEventReducer()
    seq = EventSequencer("run-ui")
    reducer.apply(seq.emit("agent_start", {"task": "x"}))
    reducer.apply(seq.emit("turn_start", {"n": 1}))
    reducer.apply(seq.emit("stream_delta", {"text": "hello"}))
    reducer.apply(seq.emit("cost", {"cost": 0.05}))
    snap = reducer.snapshot()
    assert snap["status"] == "running"
    assert snap["turn"] == 1
    assert snap["cost"] == 0.05
