"""Harness timing budgets (ms) — used by pytest and `kite bench --check`."""

from __future__ import annotations

from kite.bench.suite import BenchmarkReport

# Median wall-time ceilings for CI / local regression gates (no live LLM).
# Generous enough for Windows CI; tighten over time as the harness gets faster.
BUDGETS_MS: dict[str, float] = {
    "cli_import": 900.0,
    "config_load": 80.0,
    "user_config_load": 50.0,
    "catalog_load": 120.0,
    "skills_load": 350.0,
    "repl_chat_init": 450.0,
    "model_resolve": 400.0,
    "slash_index": 500.0,
    "repo_map": 800.0,
    "runtime_prepare": 1500.0,
    "prompt_cache_prepare": 500.0,
    "context_gather": 900.0,
    "tool_registry": 200.0,
    "read_tool": 300.0,
    "grep_tool": 800.0,
    "bash_echo": 1500.0,
    "prompt_assembly": 400.0,
    "subprocess_spawn": 2000.0,
    "job_lifecycle": 2500.0,
    "checkpoint_roundtrip": 1200.0,
}

# Full-suite measurements are diagnostic: never turn filesystem/cold-start noise into a CI gate.
FULL_BENCHMARKS = frozenset({
    "cold_cli_help", "cold_repl_import", "stream_render_50", "stream_render_80", "stream_render_120",
    "agent_turn", "large_repo_map", "large_grep", "large_completion",
    "prompt_cache_growth_50", "prompt_cache_growth_200", "agent_loop_50", "agent_loop_200",
    "stream_delta_20k", "stream_reasoning_20k", "picker_navigation_10k", "stream_render_dumb",
    "session_list_2000", "session_append_500", "session_resume_50mb", "session_tail_50mb",
    "session_recent_events", "session_reverse_row_50mb",
})

CATEGORIES = ("startup", "context", "tools")


def check_report(report: BenchmarkReport) -> list[str]:
    """Return human-readable violations for benchmarks over budget."""
    violations: list[str] = []
    for row in report.results:
        if row.metadata.get("ok") is False or row.metadata.get("roundtrip") is False or row.metadata.get("returncode", 0) != 0:
            violations.append(f"{row.name}: benchmark operation failed")
        if row.name in FULL_BENCHMARKS:
            continue
        ceiling = BUDGETS_MS.get(row.name)
        if ceiling is None:
            violations.append(f"missing budget for benchmark '{row.name}'")
            continue
        if row.ms > ceiling:
            violations.append(f"{row.name}: {row.ms:.1f}ms > {ceiling:.0f}ms budget")
    expected = set(BUDGETS_MS)
    found = {r.name for r in report.results}
    missing = expected - found
    for name in sorted(missing):
        violations.append(f"missing benchmark '{name}' in report")
    return violations
