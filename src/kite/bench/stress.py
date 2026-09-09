"""Brute-force harness stress tests — time, space, and stability (no live LLM)."""

from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.dispatch_mode import resolve_dispatch_mode
from kite.agent.orchestrator import SubagentOrchestrator
from kite.tools.jobs import JobRegistry


@dataclass(frozen=True, slots=True)
class StressResult:
    name: str
    iterations: int
    total_ms: float
    median_ms: float
    p95_ms: float
    peak_kb: float
    final_heap_kb: float
    errors: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_ms": round(self.total_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "peak_kb": round(self.peak_kb, 3),
            "final_heap_kb": round(self.final_heap_kb, 3),
            "errors": self.errors,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class StressReport:
    results: tuple[StressResult, ...]
    platform: str
    cwd: str
    passed: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "cwd": self.cwd,
            "passed": self.passed,
            "notes": self.notes,
            "results": [r.to_dict() for r in self.results],
        }


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[idx]


def _run_stress(
    name: str,
    fn,
    *,
    iterations: int,
) -> StressResult:
    tracemalloc.start()
    samples: list[float] = []
    errors = 0
    t0 = time.perf_counter()
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            fn()
        except Exception:
            errors += 1
        samples.append((time.perf_counter() - start) * 1000.0)
    total_ms = (time.perf_counter() - t0) * 1000.0
    _, peak = tracemalloc.get_traced_memory()
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    return StressResult(
        name=name,
        iterations=iterations,
        total_ms=total_ms,
        median_ms=statistics.median(samples),
        p95_ms=_percentile(samples, 0.95),
        peak_kb=peak / 1024.0,
        final_heap_kb=current / 1024.0,
        errors=errors,
    )


def run_stress_suite(*, cwd: str | Path | None = None) -> StressReport:
    """Brute-force orchestrator, dispatch, and job-registry paths."""
    import platform

    root = Path(cwd or Path.cwd()).resolve()
    notes: list[str] = []
    results: list[StressResult] = []

    def _runner(prompt: str, *, cancel=None) -> dict[str, Any]:
        return {"exit_status": "Submitted", "submission": f"ok:{prompt[:32]}"}

    orch = SubagentOrchestrator(runner=_runner, timeout_seconds=0, jobs=JobRegistry())

    def _sync_burst() -> None:
        orch.dispatch({"prompt": "stress", "label": "burst"})

    r = _run_stress("orchestrator_sync×200", _sync_burst, iterations=200)
    r = StressResult(
        name=r.name,
        iterations=r.iterations,
        total_ms=r.total_ms,
        median_ms=r.median_ms,
        p95_ms=r.p95_ms,
        peak_kb=r.peak_kb,
        final_heap_kb=r.final_heap_kb,
        errors=r.errors,
        metadata={"tasks_retained": len(orch.tasks)},
    )
    results.append(r)
    if len(orch.tasks) > 128:
        notes.append(f"orchestrator.tasks grew to {len(orch.tasks)} — consider pruning")

    orch.tasks.clear()
    orch2 = SubagentOrchestrator(runner=_runner, timeout_seconds=0, jobs=JobRegistry())

    def _crew_burst() -> None:
        orch2.dispatch(
            {
                "prompts": ["a", "b", "c"],
                "labels": ["w1", "w2", "w3"],
            }
        )

    results.append(_run_stress("orchestrator_crew×50", _crew_burst, iterations=50))

    def _async_burst() -> None:
        out = orch2.dispatch({"prompt": "bg", "background": True, "label": "bg"})
        job_id = str(out.get("job_id") or "")
        if job_id:
            orch2.dispatch({"wait_for": [job_id], "timeout_seconds": 2})

    results.append(_run_stress("orchestrator_async_e2e×30", _async_burst, iterations=30))

    prompts = [f"prompt {i}" for i in range(50)]

    def _dispatch_resolve() -> None:
        for p in prompts:
            resolve_dispatch_mode({"prompt": p, "labels": [f"l{i}" for i in range(3)]})

    results.append(_run_stress("dispatch_mode×50", _dispatch_resolve, iterations=20))

    passed = all(r.errors == 0 for r in results)
    # Soft ceilings — stress harness should stay bounded on dev laptops / CI VMs.
    for r in results:
        if r.p95_ms > 500.0 and "dispatch" not in r.name:
            notes.append(f"{r.name}: p95 {r.p95_ms:.1f}ms > 500ms soft ceiling")
            passed = False
        if r.peak_kb > 8192:
            notes.append(f"{r.name}: peak heap {r.peak_kb:.0f}KB > 8MB soft ceiling")
            passed = False

    return StressReport(
        results=tuple(results),
        platform=platform.platform(),
        cwd=str(root),
        passed=passed,
        notes=notes,
    )
