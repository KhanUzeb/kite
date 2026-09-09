"""Orchestrate A/B and stress harness benchmarks."""

from __future__ import annotations

from kite.agent.orchestrator import SubagentOrchestrator
from kite.bench.budgets import check_report
from kite.bench.orchestrate_ab import run_orchestrate_ab
from kite.bench.stress import run_stress_suite
from kite.bench.suite import run_suite


def test_suite_includes_orchestrate_benchmarks(workspace) -> None:
    report = run_suite(cwd=workspace)
    names = {r.name for r in report.results}
    assert {"task_dispatch", "orchestrator_sync", "dispatch_mode"} <= names
    assert not check_report(report)


def test_orchestrate_ab_produces_comparisons(workspace) -> None:
    report = run_orchestrate_ab(cwd=workspace, iterations=2)
    assert report.comparisons
    assert report.metrics
    winners = {c.name: c.winner for c in report.comparisons}
    assert winners["sync-vs-async-spawn"] == "async-spawn"


def test_stress_suite_passes(workspace) -> None:
    report = run_stress_suite(cwd=workspace)
    assert report.passed
    assert all(r.errors == 0 for r in report.results)


def test_orchestrator_prunes_finished_tasks() -> None:
    def runner(prompt: str, *, cancel=None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    for i in range(80):
        orch.run_one(f"p{i}", label=f"w{i}")
    assert len(orch.tasks) <= 64
