# Memory & working rhythm

Kite keeps several kinds of context. They differ by **lifetime**, **who writes them**, and **when the model sees them**.

| Layer | Storage | Who writes | In prompt by default? | Purpose |
|-------|---------|------------|------------------------|---------|
| **Session** | `~/.kite/sessions/*.jsonl` | Harness (every turn) | Yes (as chat history) | Full transcript for resume |
| **User** | `~/.kite/memory/USER.md` | You (`/user`) | **Yes**, when content exists | Global identity — name, role, comms prefs |
| **Profile** | `~/.kite/memory/PROFILE.md` | You (`/profile`) | **Yes**, when content exists | Stack, goals, constraints — global only |
| **Working rhythm** | `~/.kite/memory/WORKING.md` + episodic `style` rows | You (`/working`) + gentle session observation | **Yes**, when content exists | Soft “how you tend to work” — not rules |
| **Semantic memory** | `~/.kite/memory/MEMORY.md` (+ optional project) | You (`/remember`, `memory` tool) | **Opt-in** (`/memory`, `[memory] inject = always`) | Durable facts and preferences |
| **Episodic memory** | `episodes.sqlite` | Events (`remember`, continuity, style, …) | **Opt-in** (with semantic) | Short log of what happened |
| **Working continuity** | episodic `continuity` rows | Compaction / budget continue | Yes, when resuming a thread | Mission / done / next — task state, not identity |

---

## User & profile (global identity)

**Files (always under `~/.kite/memory/`, never per-repo):**

- `USER.md` — who you are (name, role, timezone, how you like to communicate)
- `PROFILE.md` — longer-lived context (stack, goals, pet peeves)

**REPL:** `/user` · `/user add …` · `/profile` · `/profile add …`

Injected with working rhythm when non-empty. Edit the markdown files directly anytime.

---

## Working rhythm (fluid, always in mind)

**File:** `~/.kite/memory/WORKING.md`

Optional narrative at the top + `## Signals` bullets. Examples:

- “prefers plan mode before large refactors”
- “comfortable steering mid-run”
- “iterates with several small edits”

**REPL:** `/working` · `/working add prefers terse answers`

**Behavior:**

- Injected as `# Working rhythm` when non-empty — separate from opt-in Memory.
- Framed as *soft context*: adapt to the moment; explicit instructions always win.
- After REPL turns, Kite may append gentle observations (heuristic, not LLM-extracted) to Signals and episodic `kind=style`.
- Edit `WORKING.md` directly anytime.

**Not:** weighted policy, scored profile, or instructions that override the current task.

---

## Semantic memory (facts, opt-in)

**Files:**

- `~/.kite/memory/MEMORY.md` — user-global
- `<repo>/.kite/MEMORY.md` — project-scoped

Format: freeform pin header + `## Notes` with `- [\`id\`] text` bullets.

**REPL:** `/remember [user|project] text` · `/memory` · `/forget id|substring`  
**CLI:** `kite memory --remember "…"` · `kite memory --forget "…"`

**Prompt injection:** only when you load memory this session (`/memory`, `/remember`) or `~/.kite/configs/*.toml` has:

```toml
[memory]
inject = "always"
```

The system prompt warns the model not to treat MEMORY.md as instructions unless memory was loaded.

---

## Episodic memory (event log)

**Files:**

- `~/.kite/memory/episodes.sqlite`
- `<repo>/.kite/memory/episodes.sqlite`

Kinds include `remember`, `continuity`, `style`, and other harness events. Listed with `/memory episodic` or `/episodic`.

Same opt-in rule as semantic memory when rendered into the prompt.

---

## Working continuity (task resume)

Written after context compaction or budget continue. Structured brief: mission, done, next, paths, open todos.

Injected as `# Working continuity` — **not** durable memory. Do not confuse with working rhythm (user habits) or semantic notes (facts).

---

## Sessions vs memory

| | Session JSONL | MEMORY.md / WORKING.md |
|---|---------------|------------------------|
| Content | Full chat + tool events | Curated notes |
| Resume | `/resume`, `kite resume` | N/A |
| Compaction | Summarizes old turns in-place | Unchanged on disk |

---

## Related commands

```bash
kite memory                          # list notes
kite memory --remember "prefer ruff" # append semantic note
kite sessions                        # list transcripts
kite sessions --show <id>            # inspect one session
```

REPL: `/memory` · `/user` · `/profile` · `/working` · `/remember` · `/forget` · `/compact` · `/checkpoint` · `/handoff`

**Subagents:** bundled personas in `src/kite/data/subagents/` (scout, reviewer, shell, coder, context). Custom: `~/.kite/subagents/*.md`. REPL: `/agents profiles` · live crew: `/live agents`

---

## See also

- [kite_commands.md](../kite_commands.md) — slash reference
- [CONTEXT.md](../CONTEXT.md) — glossary
- [docs/kite-system-design.md](kite-system-design.md) — module map (`memory/`)
