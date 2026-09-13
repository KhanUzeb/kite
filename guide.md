# Kite — visual guide

A practical walkthrough for using Kite well in the terminal. For the full command map see [kite_commands.md](kite_commands.md). For term definitions see [CONTEXT.md](CONTEXT.md).

---

## What you see in the REPL

Kite streams work as it happens — tools, diffs, answers — in one fluid transcript. No separate panels to manage.

```text
  › fix the auth timeout in @src/auth.py
  ▸ read  src/auth.py
  ▸ edit  src/auth.py        +4 -1
  ▸ bash  pytest tests/test_auth.py -q
  ✓ bash  18 passed · 1.8s
  • ## Done
    - raised session timeout to 30s
    ## Verification
    - ✓ pytest tests/test_auth.py — 18 passed
────────────────────────────────────────────
  build · groq/llama · ctx 42% · $0.02
```

Tool output is **collapsed by default**. `Ctrl+O` or `/expand` shows full logs. The footer shows mode, model, and cost; `/status` has the rest.

### Fullscreen workbench (`/fullscreen` or `Ctrl+Space`, terminal ≥100×30)

Optional layout with three panels — same events, no separate app:

```text
┌ kite · repo · branch · build · model ─────────────────────────┐
├ WORK ──────┬ STREAM ──────────────────┬ INSPECT ──────────────┤
│ ● running  │ ● read   src/auth.py     │ VERIFICATION          │
│ checklist  │ ✓ edit   src/auth.py     │ ✓ pytest  18 passed   │
│ turn 3     │ • assistant  Done…       │ Changes  1 file       │
├────────────┴──────────────────────────┴───────────────────────┤
│ composer below · Ctrl+Space · /fullscreen off                 │
└───────────────────────────────────────────────────────────────┘
```

```text
/fullscreen on|off|refresh
Ctrl+Space       toggle
```

While a turn runs in fullscreen, the stream panel refreshes instead of duplicating tool cards in scrollback.

---

## Start here (60 seconds)

```bash
kite setup                    # keys + default model
kite                          # open REPL
```

```text
Q: I just installed Kite. What do I type first?
A: kite setup, then kite. In the REPL try:
     /status        — model, mode, cost, session id
     /help          — essential commands
     /help all      — full map + shortcuts
     /plan          — explore before editing
     /build         — apply changes
```

---

## Plan → Build (recommended workflow)

```text
         ┌─────────┐
         │ PROMPT  │
         └────┬────┘
              ▼
         ┌─────────┐     read-only checklist
         │  PLAN   │     Ctrl+P  or  /plan
         └────┬────┘
              ▼
         ┌─────────┐     review what it found
         │ REVIEW  │     steer if wrong: Ctrl+G
         └────┬────┘
              ▼
         ┌─────────┐     edits + bash allowed
         │  BUILD  │     Ctrl+B  or  /build
         └────┬────┘
              ▼
         ┌─────────┐
         │ VERIFY  │     tests in affected package
         └─────────┘
```

### Example Q&A — new feature

```text
Q: I want to add rate limiting without breaking existing tests.

A:
  1. Ctrl+P
  2. "Add rate limiting to the API layer. List files to touch
      and tests to run. Do not edit yet."
  3. Read the checklist in the stream
  4. Ctrl+B
  5. "Implement that plan. Run tests in the affected package only."
```

### Example Q&A — quick one-shot (no REPL)

```bash
kite run --mode plan "map where auth tokens are validated"
kite run --mode build "implement the plan" --session <id>
```

---

## Prompting that works

### Attach context inline

```text
  fix the flaky test in @tests/test_auth.py
  explain @src/middleware/rate_limit.py
```

Or: `/attach path` · `/clip` (F8) · `@path` in the composer.

### Good vs vague

| Vague (slow) | Better (fast) |
|--------------|---------------|
| "fix the bug" | "fix login timeout in `src/auth.py`; run `pytest tests/test_auth.py`" |
| "add tests" | "add tests for `parse_token()`; match `tests/test_auth.py` style" |
| "refactor this" | "@src/api.py — extract validation; no behavior change; run package tests" |

### Example Q&A — steering mid-run

```text
Q: The agent is going the wrong direction but still running.

A:
  Esc or Ctrl+C     → stop this turn (session stays open)
  Ctrl+G            → stop AND send your correction as the next turn
  Enter (while busy)→ queue a follow-up for after this turn
  /tasks            → see queue + running work
```

---

## Approval (when Kite asks)

Mutating or risky actions pause for consent:

```text
  ⚠ bash  pip install requests
  [a] allow once  [s] session  [n] deny  [q] stop
```

| Key | Meaning |
|-----|---------|
| `a` / Enter (empty composer) | Allow once |
| `s` | Allow this session |
| `p` | Allow always (when offered) |
| `n` | Deny |
| `q` | Stop the run |

```text
Q: How do I stop Kite from asking on every file edit?

A: /approve auto     — auto in workspace; still prompts on risky bash
   /approve trust     — broader auto (use with care)
   /approve approve   — ask on every mutation
   /approve readonly — plan-style; no writes
```

---

## Verification (did it actually work?)

Kite tracks **evidence**, not vibes. Look for test output in the stream and the footer verification status.

```text
Q: The agent said "done" but I do not trust it.

A:
  1. Ctrl+O              → expand the last bash tool output
  2. Ask: "show the exact pytest output"
  3. Run yourself:        pytest <package> -q
  4. /undo                → revert last agent git checkpoint if needed
```

Submit is **blocked** when edits lack a passing check — you should see `submit blocked`, not silent success.

---

## Slash commands — everyday picks

```text
SESSION          MODEL / KEYS        MEMORY
────────         ───────────         ──────
/help            /setup              /user
/status          /login groq         /profile
/plan /build     /model list         /working
/tasks           /select             /remember
/stop            /keys               /memory
/expand          /refresh
/live
/live agents
```

### Example Q&A — switch model mid-session

```text
Q: I want a stronger model for one hard task.

A: /select  or  /model provider/id  or  /refresh groq
```

### Example Q&A — continue yesterday's work

```text
Q: I closed the terminal. How do I pick up?

A: kite sessions  →  kite resume <id>
   or /session list inside the REPL
```

---

## Skills & custom commands

| You type | Kite runs |
|----------|-----------|
| `/explain src/api.py` | Explain focus area |
| `/fix failing test` | Diagnose + patch |
| `/commit` | Commit skill |
| `/review` | Code review pass |
| `/research FastAPI lifespan` | Context7 + web |

```text
Q: I want a /ship command for releases.

A: /commands new ship  →  edit .kite/commands/ship.md  →  /ship 1.2.0
```

---

## Subagents & background work

```text
Q: When should I use subagents?

A:
  One agent       — most tasks
  /orchestrate    — fan-out scout + coder + reviewer
  /live agents    — stream crew output
  /jobs           — list background bash + subagents
  /kill <id>      — stop one worker
```

---

## Keyboard cheat sheet

```text
IDLE                         WHILE RUNNING
────                         ─────────────
Enter          send          Enter          queue follow-up
Tab            complete       Esc / Ctrl+C   stop turn
Ctrl+P         plan           Ctrl+G         steer
Ctrl+B         build          Ctrl+U         dequeue → composer
Ctrl+O         expand tools   /tasks         queue + status
Ctrl+T         thinking       /live          stream bash
F2             flash status   /live agents   stream crew
Ctrl+D         quit
@file          attach inline
```

---

## Context, compaction, handoff

```text
Footer:  ctx 42%  — transcript size vs model window

  /compact     summarize older turns
  /checkpoint save|list|restore
  /handoff     export for another agent
```

```text
Q: Long thread; model is forgetting early decisions.

A: /compact  →  /checkpoint save  →  /handoff  →  kite resume <id>
```

---

## One-shot & automation

```bash
kite run --headless "run pytest and report failures"
kite tasks run tasks.jsonl
kite run --attach src/foo.py "explain this module"
```

---

## Safety habits

| Do | Avoid |
|----|-------|
| `/plan` before large refactors | `kite run --no-guardrails` on untrusted input |
| `/approve auto` for daily dev | Pasting secrets into the composer |
| `/restricted on` in unknown repos | Assuming "done" without test output |

Details: [SECURITY.md](SECURITY.md)

---

## Troubleshooting

```text
Q: Agent keeps repeating the same tool call
A: Esc → steer with a different strategy; or /stop and narrow the task.

Q: No API key / model errors
A: kite keys --set <provider>  or  /login <provider>

Q: Run history later
A: kite sessions --show <id>  or  kite dashboard --session <id>
```

---

## Where to go next

| Doc | Use when |
|-----|----------|
| [kite_commands.md](kite_commands.md) | Every flag and slash |
| [CONTEXT.md](CONTEXT.md) | Glossary |
| [architecture.md](architecture.md) | How layers fit together |
| [SECURITY.md](SECURITY.md) | Sandbox, approval, redaction |

```text
Q: What is the one habit that makes Kite feel great?

A: Plan → Build → Verify. Ask for evidence. Steer early. Keep tasks scoped.
```
