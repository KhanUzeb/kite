"""Harness timing budgets (ms) — used by pytest and `kite bench --check`."""

from __future__ import annotations

from kite.bench.suite import BenchmarkReport

# Median wall-time ceilings for CI / local regression gates (no live LLM).
# Generous enough for Windows CI; tighten over time as the harness gets faster.
BUDGETS_MS: dict[str, float] = {
    "cli_import": 1200.0,
    "config_load": 80.0,
    "user_config_load": 50.0,
    "catalog_load": 120.0,
    "skills_load": 400.0,
    "repl_chat_init": 600.0,
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
}

CATEGORIES = ("startup", "context", "tools")


def check_report(report: BenchmarkReport) -> list[str]:
    """Return human-readable violations for benchmarks over budget."""
    violations: list[str] = []
    for row in report.results:
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
