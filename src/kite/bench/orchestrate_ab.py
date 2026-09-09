"""A/B harness benchmarks — task vs subagent dispatch paths (no live LLM)."""

from __future__ import annotations

import statistics
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.dispatch_mode import resolve_dispatch_mode
from kite.agent.orchestrator import SubagentOrchestrator
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools

_MAX_FINISHED_TASKS = 64
_SEARCH_PROMPTS = (
    "find auth entrypoints",
    "locate database config",
    "map test files",
)


@dataclass(frozen=True, slots=True)
class ABMetric:
    name: str
    variant: str
    wall_ms: float
    peak_kb: float
    iterations: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ABComparison:
    name: str
    metric: str
    variant_a: str
    variant_b: str
    a_ms: float
    b_ms: float
    a_peak_kb: float
    b_peak_kb: float
    delta_ms: float
    delta_pct: float
    delta_peak_kb: float
    winner: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "variant_a": self.variant_a,
            "variant_b": self.variant_b,
            "a_ms": round(self.a_ms, 3),
            "b_ms": round(self.b_ms, 3),
            "a_peak_kb": round(self.a_peak_kb, 3),
            "b_peak_kb": round(self.b_peak_kb, 3),
            "delta_ms": round(self.delta_ms, 3),
            "delta_pct": round(self.delta_pct, 2),
            "delta_peak_kb": round(self.delta_peak_kb, 3),
            "winner": self.winner,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ABReport:
    comparisons: tuple[ABComparison, ...]
    metrics: tuple[ABMetric, ...]
    platform: str
    cwd: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "cwd": self.cwd,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "metrics": [
                {
                    "name": m.name,
                    "variant": m.variant,
                    "wall_ms": round(m.wall_ms, 3),
                    "peak_kb": round(m.peak_kb, 3),
                    "iterations": m.iterations,
                    "metadata": m.metadata,
                }
                for m in self.metrics
            ],
        }


def _mock_runner(prompt: str, *, cancel=None) -> dict[str, Any]:
    # Simulate nested worker latency without LiteLLM (5ms — enough to show async win).
    time.sleep(0.005)
    _ = prompt
    return {"exit_status": "Submitted", "submission": "survey complete: " + ("." * 80)}


def _measure_variant(
    name: str,
    variant: str,
    fn: Callable[[], Any],
    *,
    iterations: int = 5,
) -> ABMetric:
    peaks: list[float] = []
    samples: list[float] = []
    meta: dict[str, Any] = {}
    for _ in range(iterations):
        tracemalloc.start()
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples.append(elapsed)
        peaks.append(peak / 1024.0)
        if isinstance(result, dict):
            meta.update({k: result[k] for k in ("ok", "subagents", "succeeded") if k in result})
    return ABMetric(
        name=name,
        variant=variant,
        wall_ms=statistics.median(samples) * 1000.0,
        peak_kb=statistics.median(peaks),
        iterations=iterations,
        metadata=meta,
    )


def _compare(
    name: str,
    metric: str,
    a: ABMetric,
    b: ABMetric,
    *,
    lower_is_better: bool = True,
    notes: str = "",
) -> ABComparison:
    delta_ms = b.wall_ms - a.wall_ms
    delta_pct = ((b.wall_ms / a.wall_ms) - 1.0) * 100.0 if a.wall_ms else 0.0
    delta_peak = b.peak_kb - a.peak_kb
    if lower_is_better:
        if abs(delta_ms) < 0.05 * max(a.wall_ms, b.wall_ms, 0.001):
            winner = "tie"
        else:
            winner = a.variant if a.wall_ms <= b.wall_ms else b.variant
    else:
        winner = b.variant if b.wall_ms >= a.wall_ms else a.variant
    return ABComparison(
        name=name,
        metric=metric,
        variant_a=a.variant,
        variant_b=b.variant,
        a_ms=a.wall_ms,
        b_ms=b.wall_ms,
        a_peak_kb=a.peak_kb,
        b_peak_kb=b.peak_kb,
        delta_ms=delta_ms,
        delta_pct=delta_pct,
        delta_peak_kb=delta_peak,
        winner=winner,
        notes=notes,
    )


def run_orchestrate_ab(*, cwd: str | Path | None = None, iterations: int = 5) -> ABReport:
    """Run task vs subagent A/B comparisons with wall-time and peak heap metrics."""
    import platform

    root = Path(cwd or Path.cwd()).resolve()
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    app = src / "app.py"
    if not app.is_file():
        app.write_text("def auth():\n    return True\n\nx = 1\n", encoding="utf-8")

    tools = make_coding_tools(cwd=str(root))
    env = LocalEnvironment(registry=ToolRegistry(tools))
    orch = SubagentOrchestrator(runner=_mock_runner, timeout_seconds=0)

    def _task_single() -> dict[str, Any]:
        return env.execute(
            {"tool": "task", "arguments": {"prompt": _SEARCH_PROMPTS[0], "pattern": "def"}}
        )

    def _task_parallel() -> dict[str, Any]:
        return env.execute(
            {
                "tool": "task",
                "arguments": {"prompts": list(_SEARCH_PROMPTS), "pattern": "def"},
            }
        )

    def _sub_sync_one() -> dict[str, Any]:
        orch.tasks.clear()
        return orch.dispatch({"prompt": _SEARCH_PROMPTS[0], "label": "scout"})

    def _sub_sync_crew() -> dict[str, Any]:
        orch.tasks.clear()
        return orch.dispatch(
            {
                "prompts": list(_SEARCH_PROMPTS),
                "labels": ["scout-a", "scout-b", "scout-c"],
            }
        )

    def _sub_async_spawn() -> dict[str, Any]:
        orch.tasks.clear()
        return orch.dispatch(
            {"prompt": "Survey in the background while I continue", "label": "async-scout"}
        )

    def _sub_async_e2e() -> dict[str, Any]:
        orch.tasks.clear()
        spawned = orch.dispatch(
            {"prompt": "background survey", "background": True, "label": "async-e2e"}
        )
        job_id = str(spawned.get("job_id") or "")
        time.sleep(0.02)
        return orch.dispatch({"wait_for": [job_id], "timeout_seconds": 5})

    def _dispatch_resolve() -> None:
        for prompt in _SEARCH_PROMPTS:
            resolve_dispatch_mode({"prompt": prompt})

    metrics: list[ABMetric] = []
    metrics.append(_measure_variant("task", "single", _task_single, iterations=iterations))
    metrics.append(_measure_variant("task", "parallel×3", _task_parallel, iterations=iterations))
    metrics.append(_measure_variant("subagent", "sync×1", _sub_sync_one, iterations=iterations))
    metrics.append(_measure_variant("subagent", "sync-crew×3", _sub_sync_crew, iterations=iterations))
    metrics.append(_measure_variant("subagent", "async-spawn", _sub_async_spawn, iterations=iterations))
    metrics.append(_measure_variant("subagent", "async-e2e", _sub_async_e2e, iterations=iterations))
    metrics.append(_measure_variant("dispatch_mode", "resolve×3", _dispatch_resolve, iterations=iterations * 3))

    by_key = {(m.name, m.variant): m for m in metrics}
    comparisons: list[ABComparison] = [
        _compare(
            "search-fanout",
            "wall_ms",
            by_key[("task", "single")],
            by_key[("task", "parallel×3")],
            notes="task parallel does real glob/grep per worker",
        ),
        _compare(
            "orchestrator-crew",
            "wall_ms",
            by_key[("subagent", "sync×1")],
            by_key[("subagent", "sync-crew×3")],
            notes="mock runner — measures thread pool + event overhead only",
        ),
        _compare(
            "sync-vs-async-spawn",
            "wall_ms",
            by_key[("subagent", "sync×1")],
            by_key[("subagent", "async-spawn")],
            notes="async should be much faster — parent does not wait for mock runner",
            lower_is_better=True,
        ),
        _compare(
            "async-spawn-vs-e2e",
            "wall_ms",
            by_key[("subagent", "async-spawn")],
            by_key[("subagent", "async-e2e")],
            notes="e2e includes wait_for poll until worker completes",
        ),
        _compare(
            "task-vs-subagent-single",
            "wall_ms",
            by_key[("task", "single")],
            by_key[("subagent", "sync×1")],
            notes="task hits disk (glob/grep); subagent is mock LLM — not interchangeable",
        ),
    ]

    return ABReport(
        comparisons=tuple(comparisons),
        metrics=tuple(metrics),
        platform=platform.platform(),
        cwd=str(root),
    )
