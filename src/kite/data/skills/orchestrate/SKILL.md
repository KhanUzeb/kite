---
name: orchestrate
description: Split multi-step work across todo_write, task, and parallel subagents without nested chaos.
---

# Orchestrate skill

Use when a task has several independent workstreams or a long checklist.

## When to use what
- `todo_write`: always for multi-step work. Keep exactly one item `in_progress`; update as you go.
- `task`: cheap parallel *code search* (glob/grep summaries). Prefer for locate/investigate, not for edits.
- `subagent`: nested LLM workers via the orchestrator. Pass `prompts` (and optional `labels`) for independent plan items. Each worker runs read-only plan mode with a bounded step budget. Tracked in `/agents` and `/jobs`; kill with `/kill`.

## Split rules
1. Write the plan with `todo_write` before spawning workers.
2. Each subagent prompt must be self-contained: goal, paths/constraints, success check. No shared mutable assumptions.
3. Give workers fun, memorable `labels` (`scout-routes`, `audit-deps`, `map-tests`) — they show in the TUI crew board.
4. Parallelize only independent items (e.g. explore A vs B). Serialize anything that shares files or ordering.
5. Cap fan-out (≈2–3 workers). Subagents cannot spawn further subagents.
6. Integrate results yourself: merge findings, then edit; don't ask workers to "also commit/PR".

## Good labels + prompts
```
labels: ["scout-auth", "scout-db"]
prompts: [
  "Read-only survey: how does auth middleware work? List entrypoints under src/auth. Summarize findings.",
  "Read-only survey: where is the DB layer configured? List files and connection flow."
]
```

## Avoid
- Spawning subagents for tiny lookups (`grep`/`task` is enough)
- Duplicate prompts that thrash the same files
- Leaving todos stale after workers finish
- Expecting `submit` from explorers — useful text counts as success
