# Kite — visual guide

A practical walkthrough for using Kite well in the terminal. For the full command map see [kite_commands.md](kite_commands.md). For term definitions see [CONTEXT.md](CONTEXT.md).

---

## What you are looking at

Kite is a **run-centric agent cockpit**, not a chat app. Each task is a **Run**:

```text
┌─────────────────────────────────────────────────────────────┐
│  YOU: "fix the auth timeout, run tests, show evidence"      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐
│   Goal   │ → │   Plan   │ → │  Actions │ → │ Verification │
└──────────┘   └──────────┘   └──────────┘   └──────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │   Changes    │  (+/− per file)
                        └──────────────┘
```

**Good outcome:** you can answer *what changed*, *what was run*, and *why it is correct* — without reading a wall of logs.

---

## Two layouts (same run, same events)

### Compact (default)

Dense transcript. Keyboard-first. Best for SSH and small terminals.

```text
  › fix auth timeout in @src/auth.py
  ▸ read  src/auth.py
  ▸ edit  src/auth.py
  ▸ bash  pytest tests/test_auth.py -q
  ✓ bash  18 passed
  • Done — session timeout raised to 30s …
────────────────────────────────────────────
  build · groq/llama · ctx 42% · $0.02
```

### Cockpit (`/cockpit` or `Ctrl+Space`, terminal ≥100×30)

Persistent panels. Best when you want status at a glance.

```text
┌ KITE  my-app  main  build  llama ────────────────────────────┐
├ WORK ──────┬ RUN ─────────────────────┬ INSPECT ────────────┤
│ ● Running  │ Goal: fix auth timeout   │ VERIFICATION        │
│ Turn 3     │ Plan  ✓ 2/3              │ ✓ pytest  18/18     │
│            │ Timeline                 │ Changes  1 file     │
│ CREW       │  ✓ read                  │ auth.py  +4 -1      │
│            │  ✓ edit                  │                     │
│            │  ● verify                │ Status: running     │
├────────────┴──────────────────────────┴─────────────────────┤
│ [@src/auth] [build] [llama]              [Plan] [Build]     │
└─────────────────────────────────────────────────────────────┘
```

```text
/cockpit           toggle compact ↔ cockpit
/cockpit on|off    force a mode
/cockpit refresh   redraw panels
```

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
     /help          — full map + shortcuts
     /plan          — explore before editing
     /build         — apply changes
     /cockpit       — run layout (big terminal)
```

---

## Plan → Build (recommended workflow)

```text
         ┌─────────┐
         │ PROMPT  │
         └────┬────┘
              ▼
         ┌─────────┐     read-only: checklist, no writes
         │  PLAN   │     Ctrl+P  or  /plan
         └────┬────┘
              ▼
         ┌─────────┐     you review todos in the stream
         │ REVIEW  │     steer if wrong: Ctrl+G + correction
         └────┬────┘
              ▼
         ┌─────────┐     mutating tools allowed
         │  BUILD  │     Ctrl+B  or  /build
         └────┬────┘
              ▼
         ┌─────────┐
         │ VERIFY  │     agent runs tests in affected package
         └────┬────┘
              ▼
         ┌─────────┐
         │ REVIEW  │     /cockpit → Changes + Verification
         └─────────┘
```

### Example Q&A — new feature

```text
Q: I want to add rate limiting without breaking existing tests. Best flow?

A:
  1. Ctrl+P                    → plan mode
  2. "Add rate limiting to the API layer. List files to touch
      and tests to run. Do not edit yet."
  3. Read the checklist        → confirm scope
  4. Ctrl+B                    → build mode
  5. "Implement the plan. Run tests in the affected package only."
  6. /cockpit                  → inspect Changes + Verification
```

### Example Q&A — quick one-shot (no REPL)

```bash
kite run --mode plan "map where auth tokens are validated"
kite run --mode build "implement the plan from last session" --session <id>
```

---

## Prompting that works

### Attach context inline

```text
  fix the flaky test in @tests/test_auth.py
  explain @src/middleware/rate_limit.py
  compare @src/old.py and @src/new.py
```

Or queue files: `/attach path/to/file` · `/clip` (F8) · drag path into terminal as `@path`.

### Good vs vague

| Vague (slow) | Better (fast) |
|--------------|---------------|
| "fix the bug" | "fix login timeout in `src/auth.py`; keep patch minimal; run `pytest tests/test_auth.py`" |
| "add tests" | "add tests for `parse_token()` edge cases; match `tests/test_auth.py` style" |
| "refactor this" | "@src/api.py — extract validation to `validators.py`; no behavior change; run package tests" |

### Example Q&A — steering mid-run

```text
Q: The agent is going the wrong direction but still running.

A:
  Esc or Ctrl+C     → stop this turn (session stays open)
  Ctrl+G            → stop AND send your correction as the next turn
  Enter (while busy)→ queue a follow-up for after this turn
  /tasks            → see queue + running work
```

```text
  [you type while agent runs]
  "Stop — use edit not write. Only change the timeout constant."
  [Enter queues it]

  or: Ctrl+G with that text in the composer for immediate steer
```

---

## Approval (when Kite asks)

High-risk or out-of-scope actions float to a **foreground card** — not buried in logs.

```text
┌─ Approval ─────────────────────────────────────┐
│ ⚠ Approval required                            │
│ bash                                           │
│ pip install requests                           │
│                                                │
│ scope: workspace                               │
│ risk: package install                          │
│                                                │
│ [a] allow once  [s] session  [n] deny  [q] stop│
└────────────────────────────────────────────────┘
```

| Key | Meaning |
|-----|---------|
| `a` / Enter (empty composer) | Allow once |
| `s` | Allow this session |
| `p` | Allow always (pattern; when offered) |
| `n` | Deny |
| `q` | Stop the run |

```text
Q: How do I stop Kite from asking on every file edit?

A: /approve auto     — auto in workspace; still prompts on risky bash
   /approve trust     — broader auto (use with care)
   /approve approve   — ask on every mutation
   /approve readonly — plan-style; no writes
```

Headless / CI: approval modes that need a human (`approve`, `readonly`) upgrade or deny — use `auto` for scripted runs.

---

## Verification (did it actually work?)

Kite tracks **evidence**, not vibes. The inspect panel shows:

```text
VERIFICATION
✓ pytest        18/18
✓ lint          pass
✗ typecheck     2 errors        ← run shows Unverified until fixed
```

```text
Q: The agent said "done" but I do not trust it.

A:
  1. /cockpit              → Verification + Changes panels
  2. Ask: "show the exact command output for the test run"
  3. Run yourself:         pytest <package> -q
  4. /undo                 → revert last agent git checkpoint if needed
```

Submit is **blocked** when edits lack a passing check — you should see `submit blocked` or an unverified badge, not silent success.

---

## Slash commands — everyday picks

```text
SESSION          MODEL / KEYS        MEMORY
────────         ───────────         ──────
/help            /setup              /user
/status          /login groq         /profile
/plan /build     /model list         /working
/cockpit         /select             /remember
/tasks           /reasoning          /memory
/stop            /keys               /forget
/expand          /refresh
/live
/live agents
```

### Example Q&A — switch model mid-session

```text
Q: Groq is fast but I want a stronger model for one hard task.

A:
  /select                  → interactive picker (saved to ~/.kite/config.toml)
  /model provider/id       → one-off switch
  /refresh groq            → re-fetch live models, then pick
```

### Example Q&A — continue yesterday's work

```text
Q: I closed the terminal. How do I pick up?

A:
  kite sessions            → table of transcripts
  kite resume <id>         → reopen in REPL
  kite resume <id> "also add logging"
  /session list            → same, inside REPL
```

---

## Skills & custom commands

Bundled prompts you type as slashes:

| You type | Kite runs |
|----------|-----------|
| `/explain src/api.py` | Explain focus area |
| `/fix failing test` | Diagnose + patch |
| `/commit` | Commit skill (conventional message) |
| `/review` | Code review pass |
| `/test` | Test-focused workflow |
| `/research FastAPI lifespan` | Context7 + web |

Add your own:

```text
Q: I want a /ship command for releases.

A:
  /commands new ship       → writes .kite/commands/ship.md
  edit the markdown        → your playbook; $ARGUMENTS = rest of line
  /ship 1.2.0              → becomes the next user turn
```

Project commands override user commands with the same name. See [kite_commands.md §3](kite_commands.md#3-prompt-slashes-skills-markdown-commands-plugins).

---

## Subagents & background work

```text
CREW (cockpit / /agents)
● scout        completed   "map auth module"
● coder        running     "implement retry"
○ reviewer     queued
```

```text
Q: When should I use subagents vs one agent?

A:
  One agent     — most tasks; simpler trace
  /orchestrate  — fan-out: scout + coder + reviewer
  /live agents  — stream crew output with worker prefix
  /jobs         — list background bash + subagents
  /kill <id>    — stop one worker
```

Prefer **bundled profiles** (`scout`, `reviewer`, `shell`, `coder`, `context`) over tiny one-off workers.

---

## Keyboard cheat sheet

```text
IDLE                         WHILE RUNNING
────                         ─────────────
Enter          send          Enter          queue follow-up
Tab            complete       Esc / Ctrl+C   stop turn
Ctrl+Space     cockpit        Ctrl+G         steer (stop + send)
Ctrl+P         plan           Ctrl+U         dequeue → composer
Ctrl+B         build          /tasks         queue + status
Ctrl+O         expand tools   /live          stream bash
Ctrl+T         thinking       /live agents   stream crew
F2             flash status
Ctrl+D         quit
@file          attach inline
```

---

## Context, compaction, handoff

```text
Context meter (footer):  ctx 42%  — transcript size vs model window

  /compact     summarize older turns now
  /checkpoint save|list|restore
  /handoff     export .kite/handoff-* for another agent or human
```

```text
Q: Long thread; model is forgetting early decisions.

A:
  /compact                 → shrink history, keep facts
  /checkpoint save pre-refactor
  /handoff                 → export brief + snapshot
  kite resume <id>         → continue in a fresh session with same id
```

---

## One-shot & automation

```bash
# CI-style quiet run (stderr events only)
kite run --headless "run pytest and report failures"

# Batch file
kite tasks run tasks.jsonl

# Attach files from CLI
kite run --attach src/foo.py "explain this module"
```

```text
Q: Run the same prompt 10 times overnight?

A: Put one JSON object per line in tasks.jsonl:
     {"task": "…", "label": "run-1", "mode": "build", "cwd": "/path"}
   kite tasks run tasks.jsonl --approval auto
```

---

## Safety habits

| Do | Avoid |
|----|-------|
| `/plan` before large refactors | `kite run --no-guardrails` on untrusted input |
| `/approve auto` for daily dev | Pasting secrets into the composer |
| `/restricted on` in unknown repos | Assuming "done" without verification panel |
| `/privacy` to control session disk | Ignoring approval cards for `curl` / `pip install` |

Details: [SECURITY.md](SECURITY.md)

---

## Troubleshooting

```text
Q: "Terminal too small for cockpit"
A: Widen to ≥100 cols × 30 rows, or stay in compact mode.

Q: Agent keeps repeating the same tool call
A: Esc → steer with a different strategy; or /stop and narrow the task.

Q: No API key / model errors
A: kite keys --set <provider>  or  /login <provider>

Q: Want human-readable run history later
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
| [AGENTS.md](AGENTS.md) | Hacking on Kite itself |

```text
Q: What is the one habit that makes Kite feel great?

A: Plan → Build → Verify → Review in the cockpit.
   Ask for evidence. Steer early. Keep tasks scoped.
```
