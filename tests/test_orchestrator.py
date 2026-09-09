"""Subagent orchestrator — dispatch, success semantics, parallel fan-out."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from kite.agent.cancel import CancelToken
from kite.agent.orchestrator import (
    SubagentOrchestrator,
    evaluate_subagent_result,
    worker_glyph,
)


def test_worker_glyph_rotates() -> None:
    assert worker_glyph(1) == "◆"
    assert worker_glyph(2) == "●"
    assert worker_glyph(7) == worker_glyph(1)


def test_evaluate_subagent_result_submitted() -> None:
    ok, quality, summary = evaluate_subagent_result(
        {"exit_status": "Submitted", "submission": "all good"}
    )
    assert ok is True
    assert quality == "done"
    assert summary == "all good"


def test_evaluate_subagent_result_partial_findings() -> None:
    text = "x" * 50
    ok, quality, _ = evaluate_subagent_result({"exit_status": "LimitsExceeded", "submission": text})
    assert ok is True
    assert quality == "done"


def test_evaluate_subagent_result_failed_error() -> None:
    ok, quality, _ = evaluate_subagent_result({"exit_status": "Error", "error": "boom"})
    assert ok is False
    assert quality == "failed"


def test_run_one_emits_events_and_manager_view() -> None:
    events: list[tuple[str, dict]] = []

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": f"done: {prompt[:20]}"}

    orch = SubagentOrchestrator(
        runner=runner,
        on_event=lambda e: events.append((e.kind, dict(e.payload))),
        timeout_seconds=0,
    )
    out = orch.run_one("explore auth module", label="scout")
    assert out["ok"] is True
    assert out["quality"] == "done"
    kinds = [k for k, _ in events]
    assert "subagent_start" in kinds
    assert "subagent_end" in kinds
    assert orch.manager_view()[-1]["label"] == "scout"
    assert orch.manager_view()[-1]["glyph"]


def test_run_parallel_orders_sections_and_counts_delivered() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        if "fail" in prompt:
            return {"exit_status": "Error", "error": "nope"}
        return {"exit_status": "Submitted", "submission": prompt}

    events: list[str] = []
    orch = SubagentOrchestrator(
        runner=runner,
        on_event=lambda e: events.append(e.kind),
        max_workers=2,
        timeout_seconds=0,
    )
    out = orch.run_parallel(
        ["scan a", "scan fail", "scan b"],
        labels=["alpha", "broken", "beta"],
    )
    assert out["succeeded"] == 2
    assert out["ok"] is False
    assert "crew report" in out["output"]
    assert "succeeded" in out["output"]
    assert "alpha" in out["output"]
    assert "orchestrator_start" in events
    assert "orchestrator_end" in events


def test_dispatch_requires_prompt() -> None:
    orch = SubagentOrchestrator(runner=MagicMock())
    out = orch.dispatch({})
    assert out["ok"] is False


def test_kill_requests_cancel_on_running_task() -> None:
    from kite.agent.orchestrator import SubagentTask

    token = CancelToken()
    orch = SubagentOrchestrator(runner=MagicMock(), timeout_seconds=0)
    orch.tasks.append(
        SubagentTask(id="abc12345", prompt="p", label="worker", status="running", cancel=token)
    )
    assert orch.kill("abc12345") is True
    assert token.is_set()


def test_run_one_background_returns_immediately() -> None:
    def slow_runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        time.sleep(0.3)
        return {"exit_status": "Submitted", "submission": "late"}

    orch = SubagentOrchestrator(runner=slow_runner, timeout_seconds=0)
    started = time.monotonic()
    out = orch.run_one_background("explore", label="scout")
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    assert out["background"] is True
    assert out["job_id"]
    assert out["dispatch"] == "async"


def test_wait_for_collects_background_result() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        time.sleep(0.05)
        return {"exit_status": "Submitted", "submission": f"findings: {prompt}"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    spawned = orch.run_one_background("auth paths", label="scout")
    job_id = str(spawned["job_id"])
    out = orch.wait_for([job_id], timeout_seconds=5)
    assert job_id not in out.get("pending", [])
    assert "findings" in out["output"]
    assert out["results"][job_id]["ok"] is True


def test_dispatch_auto_async_from_prompt() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    out = orch.dispatch(
        {"prompt": "Run a read-only survey in the background while I continue refactoring."}
    )
    assert out.get("background") is True
    assert out.get("dispatch_reason") == "auto-async"
    assert "dispatch_hint" in out


def test_kill_all_updates_running_tasks() -> None:
    from kite.agent.orchestrator import SubagentTask

    token_a = CancelToken()
    token_b = CancelToken()
    orch = SubagentOrchestrator(runner=MagicMock(), timeout_seconds=0)
    orch.tasks.extend(
        [
            SubagentTask(id="a1", prompt="p", label="w1", status="running", cancel=token_a),
            SubagentTask(id="b2", prompt="p", label="w2", status="running", cancel=token_b),
            SubagentTask(id="c3", prompt="p", label="w3", status="finished", cancel=CancelToken()),
        ]
    )
    assert orch.kill_all() == 2
    assert token_a.is_set()
    assert token_b.is_set()


def test_wait_for_rejects_prompt_combo() -> None:
    orch = SubagentOrchestrator(runner=MagicMock(), timeout_seconds=0)
    out = orch.dispatch({"wait_for": ["abc"], "prompt": "also run this"})
    assert out["ok"] is False
    assert "cannot be combined" in out["output"]


def test_orchestrator_prunes_finished_tasks() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    for i in range(80):
        orch.run_one(f"p{i}", label=f"w{i}")
    assert len(orch.tasks) <= 64
