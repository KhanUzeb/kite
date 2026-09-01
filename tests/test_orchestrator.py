"""Subagent orchestrator dispatch."""

from __future__ import annotations

import time

from kite.agent.orchestrator import SubagentOrchestrator


def test_run_parallel_collects_results() -> None:
    events: list[str] = []

    def runner(prompt: str) -> dict:
        return {"exit_status": "Submitted", "submission": f"done:{prompt}"}

    orch = SubagentOrchestrator(
        runner=runner,
        on_event=lambda e: events.append(e.kind),
        max_workers=2,
    )
    results = orch.run_parallel(["a", "b"])
    assert results["ok"] is True
    assert results["subagents"] == 2
    assert len(orch.tasks) == 2
    assert "subagent_start" in events
    assert "subagent_end" in events


def test_run_one_failure_marks_task_failed() -> None:
    def runner(_prompt: str) -> dict:
        raise RuntimeError("boom")

    orch = SubagentOrchestrator(runner=runner)
    out = orch.run_one("fail", label="test")
    assert out["ok"] is False
    assert orch.tasks[-1].status == "failed"


def test_run_one_timeout() -> None:
    def runner(_prompt: str) -> dict:
        time.sleep(2)
        return {"exit_status": "Submitted"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=1)
    out = orch.run_one("slow", label="slow")
    assert out["ok"] is False
    assert out.get("error") == "timeout"
    assert orch.tasks[-1].status == "failed"
