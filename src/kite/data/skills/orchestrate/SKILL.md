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
| Read code and summarize tradeoffs | `subagent` with `profile=` |
| Multi-step checklist | `todo_write` / `todo_read` |

- `subagent`: nested LLM workers. **Prefer bundled profiles** (`scout`, `reviewer`, `shell`, `coder`, `context`) over microscopic JIT workers. **Sync by default** — parent waits for merged findings. `background=true` when the parent should keep working; collect with `wait_for: [job_id, ...]`. List profiles: `/agents profiles`. Monitor: `/agents`, `/live agents`. Stop: `/kill`. Max **12** workers per dispatch.

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
4. Parallelize only independent items. Cap fan-out at ≈2–3 workers (hard max 12).
5. Use `profile=` for role-shaped work (`scout` explore, `reviewer` diff review, `shell` diagnostics, `coder` implement).
6. Subagents cannot spawn further subagents or write global memory.
7. Integrate results yourself — merge findings, then edit.

## Example crew (sync, with profiles)

```
profiles: ["scout", "scout"]
labels: ["scout-auth", "scout-db"]
prompts: [
  "How does auth middleware work? List entrypoints under src/auth.",
  "Where is the DB layer configured? List files and connection flow."
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
