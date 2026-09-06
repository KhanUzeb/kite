# Adaptive budget + smart continuity memory

**Date:** 2026-09-06  
**Status:** implemented  
**Plan:** `docs/superpowers/plans/2026-09-06-adaptive-budget-smart-memory.md`

## Problem

Long coding turns in Kite chat hit `LimitsExceeded` (default 40 steps / $5) and pause. Users must type again. Compaction/`/compact` and memory exist but do not automatically carry “what’s done / what’s next” across budget continues or context shrinks the way Codex/Pi-style agents do. Looping forever is unacceptable.

## Goals

1. **Deeper useful turns** in interactive chat without raising non-interactive `kite run` blindly.
2. **Adaptive auto-continue** when a turn hits step/cost budget with unfinished work — capped, never infinite.
3. **Smart continuity memory** (Codex/Pi-ish): structured brief on compact / budget-continue; inject into the next turn; preserve facts under compaction.
4. **Keep anti-spiral controls:** LoopGuard hard-stop, idle stall, max auto-continues.

## Non-goals

- Full retrieval-ranked “memory OS” or a separate memory agent.
- Removing step/cost limits entirely.
- Changing approval/sandbox policy.
- Auto-continuing after `Submitted`, user interrupt, provider fault, or hard loop stop.

## Current baseline (reference)

| Knob | Today |
|------|--------|
| Chat/REPL step/cost | Same as runtime defaults: 40 / $5 |
| `long_task` | 120 / $25 when explicitly enabled |
| Auto-compact | ~80% ratio; checkpoint ~72% |
| Memory | MEMORY.md semantic + SQLite episodic; rendered into system prompt at run start |
| Anti-loop | LoopGuard hard-stop (~5 identical tools); stall after 2 idle no-tool turns |
| Budget UX | Soft pause; session kept; user types to continue |

## Design

### 1. Adaptive turn budget (interactive only)

**Base budget for interactive chat/REPL** (when `interactive=True` / ChatSession harness):

- Apply interactive floors **only when the effective config still uses package defaults** (40 steps / $5.0), or when interactive_* knobs are set higher.
- If the user explicitly set `step_limit` / `cost_limit` below those floors in `~/.kite/config.toml`, **honor the user’s lower caps** (no silent bump).
- Otherwise effective interactive budget ≈ 80 steps / $10 (or `interactive_step_limit` / `interactive_cost_limit` when configured).

Non-interactive `kite run` keeps existing defaults unless `--long-task` / explicit flags.

**Auto-continue (budget resume):**

When exit status is `LimitsExceeded` (step or cost) **and** unfinished work is detected:

1. Write a continuity brief (see §2).
2. Optionally force-compact if context ≥ compact ratio.
3. Start a **follow-up turn** in the same session with a synthetic user/system nudge: continue from continuity brief + open todos.
4. Reset per-turn `n_calls` / cost counters (already true for new agent instances).
5. Increment `budget_continues` for this user turn chain.

**Unfinished work heuristic (any one true):**

- Todo list has `pending` or `in_progress` items, **or**
- Last turn used tools and exit was not `Submitted` / `Interrupted` / `Stalled` / hard loop.

**Caps:**

- `max_budget_continues = 2` per user-initiated turn chain.
- After 2 continues → soft pause with clear toolbar/message (existing LimitsExceeded soft UX).
- User message / Esc / Ctrl+G always wins over auto-continue.
- Queued inbox messages: if user queued text, prefer draining inbox over silent auto-continue.

**Config knobs** (runtime + user config, with defaults):

```toml
# interactive chat defaults (effective max with config)
interactive_step_limit = 80
interactive_cost_limit = 10.0
max_budget_continues = 2
```

### 2. Smart continuity memory (Codex/Pi-style)

**Continuity brief** — short structured text (not full transcript):

```text
## Continuity
- Mission: …
- Done: …
- Next: …
- Constraints: …
- Paths: …
- Open todos: …
```

**When to write:**

- After successful auto-compact (force or ratio).
- Before each budget auto-continue.
- Existing `/handoff` remains manual export; may reuse the same builder.

**Where to store:**

- Episodic episode with `kind="continuity"` (session_id, cwd, summary + payload JSON).
- If brief contains durable project facts (paths/constraints) and user/project MEMORY is short, optionally append **one** high-signal bullet to project MEMORY.md (dedupe by text); never spam.

**When to inject:**

- Next agent run in the same session: include last continuity brief + open todos in assembled context (alongside existing `MemoryStore.render_for_prompt()`).
- Budget continue turn: inject as the follow-up content / instance addendum.

**Compaction timing:**

- Keep auto-checkpoint at **~72%**.
- Lower default `compaction_ratio` from **0.80 → 0.75** so compact happens before thrash.
- Preserve-facts + LLM/deterministic summary unchanged; continuity brief must survive as preserved content or be re-written after compact.

### 3. Anti-spiral (hard rules)

| Guard | Behavior |
|-------|----------|
| `max_budget_continues` | ≤ 2 then soft pause |
| LoopGuard | Existing hard-stop; do **not** auto-continue on hard-stop |
| Idle stall | Existing `_MAX_IDLE_TURNS`; no auto-continue on `Stalled` |
| User stop | No auto-continue on `Interrupted` |
| Submitted | No auto-continue |

### 4. UI / UX

- Soft pause message already improved; on auto-continue show a muted line: `budget continue 1/2 — resuming…`
- Toolbar running label updates (`budget continue`, then normal thinking/working).
- Composer stays pinned (prior fix); queue still works during continue.

### 5. Layering / files (implementation map)

| Area | Likely touch |
|------|----------------|
| Continuity builder | New `memory/continuity.py` (or extend `handoff.py`) |
| Episodic kind | `memory/episodic.py` / `store.py` |
| Compact thresholds | `data/configs/default.toml`, `config/runtime.py`, `config/user.py` |
| Interactive budgets + continue | `agent/runtime.py`, `agent/harness.py`, `ui/repl.py` `_run_task` |
| Context inject | `agent/runtime.py` assemble path |
| Docs | `docs/cli-ux.md`, `kite_commands.md` if new knobs/UX |
| Tests | unit tests for unfinished heuristic, continue cap, continuity write/inject, compact ratio |

## Success criteria

1. Interactive chat can run longer before first soft pause (~80 steps).
2. Hitting budget with open todos auto-resumes ≤2 times with continuity context.
3. After compact or continue, model still sees done/next/todos (not a blank slate).
4. Identical tool loops still hard-stop; no third silent auto-continue.
5. Non-interactive `kite run` defaults unchanged unless flags say otherwise.

## Risks / mitigations

| Risk | Mitigation |
|------|------------|
| Auto-continue burns cost | Cap at 2; never bump above user-set lower limits |
| Continuity noise in MEMORY.md | Episodic-first; semantic append only when high-signal + deduped |
| Double-compact thrash | Checkpoint + compact thresholds stay ordered (72% then 75%) |
| REPL complexity | Keep continue loop inside `_run_task` / harness, not a second agent type |

## Clarification on user cost overrides

If `UserConfig.step_limit` / `cost_limit` are explicitly set below interactive floors, **honor the user’s lower caps** (no silent bump). Interactive floors apply when using package defaults (40 / 5.0) or when interactive limits are configured higher.

## Out of scope follow-ups

- Semantic retrieval ranking across projects.
- Cross-session “mission” graph UI.
- Raising orchestrator/subagent budgets (separate change).
