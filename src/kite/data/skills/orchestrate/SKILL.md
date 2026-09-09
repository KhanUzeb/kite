---
name: orchestrate
description: Split multi-step work across todo_write, task, and parallel subagents without nested chaos.
---

# Orchestrate skill

Use when a task has several independent workstreams or a long checklist.

## When to use what

| Need | Tool |
|------|------|
| Find files/symbols, no reasoning | `task` |
| Read code and summarize tradeoffs | `subagent` |
| Multi-step checklist | `todo_write` / `todo_read` |

- `subagent`: nested LLM workers. **Sync by default** — parent waits for merged findings. `background=true` when the parent should keep working; collect with `wait_for: [job_id, ...]`. Tracked in `/agents` and `/jobs`; stop with `/kill`.

## Sync vs async dispatch

| Situation | Dispatch |
|-----------|----------|
| Need findings before next edit | **sync** (default) |
| Explore while parent continues | **async** — `background=true` or “in the background while I …” |
| Parallel `prompts[]` crew | **sync** unless `background=true` |
| Collect async workers | `subagent` with `wait_for: ["abc12345", ...]` |

## Split rules

1. Write the plan with `todo_write` before spawning workers.
2. Each subagent prompt must be self-contained: goal, paths/constraints, success check.
3. Use short, distinctive `labels` (`scout-auth`, `map-tests`) — they appear in `/agents` and the crew board.
4. Parallelize only independent items. Cap fan-out at ≈2–3 workers.
5. Subagents cannot spawn further subagents.
6. Integrate results yourself — merge findings, then edit.

## Example crew (sync)

```
labels: ["scout-auth", "scout-db"]
prompts: [
  "Read-only: how does auth middleware work? List entrypoints under src/auth.",
  "Read-only: where is the DB layer configured? List files and connection flow."
]
```

## Example async + collect

```
subagent prompt="Survey auth routes in the background while I refactor CLI" label="scout-auth"
# ... parent continues ...
subagent wait_for=["a1b2c3d4"] timeout_seconds=120
```

## Avoid

- Subagents for tiny lookups (`task` is enough)
- Duplicate prompts that thrash the same files
- Stale todos after workers finish
- Combining `wait_for` with new `prompt` / `prompts` in one call
