---
name: orchestrate
description: Split multi-step work across todo_write, task, and parallel subagents without nested chaos.
---

# Orchestrate skill

Use when a task has several independent workstreams or a long checklist. Do not orchestrate a single-file change.

## When to use what

| Need | Tool |
|------|------|
| Find files/symbols, no reasoning | `task` |
| Read code and summarize tradeoffs | `subagent` with `profile=` |
| Multi-step checklist | `todo_write` / `todo_read` |

Prefer bundled profiles (`scout`, `reviewer`, `shell`, `coder`, `context`) over one-off workers. Sync is the default — the parent waits. Use `background=true` only when the parent can keep working, then collect with `wait_for`. List profiles: `/agents profiles`. Monitor: `/agents`, `/live agents`. Stop: `/kill`. Hard max **12** workers per dispatch.

## Sync vs async

| Situation | Dispatch |
|-----------|----------|
| Need findings before the next edit | **sync** (default) |
| Explore while the parent continues | **async** — `background=true` |
| Parallel `prompts[]` crew | **sync** unless `background=true` |
| Collect async workers | `subagent` with `wait_for: ["abc12345", ...]` |

## Split rules
1. Write the plan with `todo_write` before spawning anyone.
2. Each prompt is self-contained: goal, paths, constraints, and how to tell it succeeded. Workers do not see this conversation.
3. Give short, distinctive `labels` (`scout-auth`, `map-tests`) — they show in `/agents`.
4. Parallelize only independent work. Aim for 2–3 workers; never the same files twice.
5. Match the profile to the job: `scout` explore, `reviewer` diff review, `shell` diagnostics, `coder` implement, `context` gather a decision.
6. Workers cannot spawn their own workers or write global memory.
7. Integrate yourself: merge findings, resolve contradictions, then edit. Do not paste worker output through as the answer.

## Avoid
- A subagent for a lookup `task` or `grep` can answer
- Duplicate prompts that thrash the same files
- Leaving todos stale after workers finish
- Combining `wait_for` with new `prompt` / `prompts` in one call
