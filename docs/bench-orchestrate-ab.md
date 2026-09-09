# Harness A/B and stress benchmarks (task vs subagent)

Repeatable **time and space** metrics for orchestration paths — **no live LLM calls**.

## Commands

```bash
# A/B: task vs subagent dispatch variants
kite bench --ab
kite bench --ab --json --save orchestrate-ab.json

# Brute-force stress (sync burst, crew burst, async e2e, dispatch resolve)
kite bench --stress
kite bench --stress --json
```

**Not part of the official pytest suite** — run manually when tuning orchestration. CI still gates the core harness via `tests/test_bench.py` and `kite bench --check`.

## A/B variants

| Variant | What it measures |
|---------|------------------|
| `task` single | One glob/grep fan-out (real disk I/O) |
| `task` parallel×3 | Three parallel glob/grep workers |
| `subagent` sync×1 | Mock nested worker — orchestrator overhead only |
| `subagent` sync-crew×3 | Parallel mock crew (thread pool + events) |
| `subagent` async-spawn | Fire-and-forget return latency |
| `subagent` async-e2e | Spawn + `wait_for` poll until done |
| `dispatch_mode` resolve×3 | Auto sync/async inference (compiled regex) |

## A/B comparisons (winner = lower wall time unless noted)

| Comparison | A | B | Notes |
|------------|---|---|-------|
| `search-fanout` | task single | task parallel×3 | Real grep/glob per worker |
| `orchestrator-crew` | sync×1 | sync-crew×3 | Mock runner — pool overhead |
| `sync-vs-async-spawn` | sync×1 | async-spawn | Async should win (no wait) |
| `async-spawn-vs-e2e` | async-spawn | async-e2e | E2E adds wait_for polling |
| `task-vs-subagent-single` | task single | sync×1 | Not interchangeable — different work |

### Metrics per variant

- **wall_ms** — median wall time per iteration
- **peak_kb** — median peak Python heap (tracemalloc) per iteration

## Stress suite

| Case | Iterations | What it hammers |
|------|------------|-----------------|
| `orchestrator_sync×200` | 200 | Sequential mock subagent dispatch |
| `orchestrator_crew×50` | 50 | 3-worker parallel crews |
| `orchestrator_async_e2e×30` | 30 | background spawn + wait_for |
| `dispatch_mode×50` | 20×50 prompts | Regex dispatch inference |

### Soft ceilings (stress `--check` implicit)

- p95 &gt; 500ms per iteration (except dispatch_mode) → fail
- peak heap &gt; 8MB → fail
- any uncaught exception → fail

## Improvements applied (from profiling)

1. **Orchestrator task pruning** — retain at most 64 finished `SubagentTask` rows (stress `tasks_retained` stays bounded).
2. **Compiled dispatch regex** — `dispatch_mode` patterns pre-compiled at import (stress p95 stable under burst).
3. **Shared runner pool** — orchestrator reuses one `ThreadPoolExecutor` for per-worker timeouts (no nested pool per crew member).

## Interpreting results

- **task** benchmarks include filesystem work; use for code-search fan-out decisions.
- **subagent** benchmarks use a mock runner; use for orchestrator/TUI overhead only.
- Choose **async** when spawn latency matters and integration can wait (`wait_for`).
- Choose **sync crew** when the parent needs merged findings before the next edit.

Save baselines before/after refactors:

```bash
kite bench --save before.json
# … change …
kite bench --compare before.json
kite bench --ab --save ab-after.json
```
