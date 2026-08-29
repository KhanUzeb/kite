# Kite CLI UX

**Agent:** kite  
**Version:** 0.4.0  
**Language:** Python · Rich (single-column, not a full-screen Textual app)  
**Companion:** [kite-system-design.md](kite-system-design.md) (architecture, atlas, tradeoffs)

Optimize for **trust, legibility, and speed of comprehension**. The user should always know what the agent is doing, why, and be able to stop or steer it in under a second.

Patterns stolen, not invented:

| Harness | What we took |
|---------|----------------|
| Claude Code | Collapsible tool blocks; live todo list; unified diffs; exact-command permission prompts; `KITE.md` project memory |
| Codex CLI | Approval mode in the prompt itself (`auto` / `approve` / `readonly`) |
| Aider | Git commit per todo/task; `/undo`; running cost in the status line |
| Gemini CLI / opencode | Single-column, keyboard-first, theme-aware (`ansi_dark` / `ansi_light`), lazy context after the prompt is live |

## Modes

| Mode | Tools | Approval default | What it produces |
|------|--------|------------------|------------------|
| **plan** | read, grep, glob, ls, task, webfetch, skill, memory, todo_* | `readonly` | A live checklist. No file mutations. |
| **build** | all tools | `approve` (chat) / `auto` (one-shot `kite run`) | Diffs, git checkpoints, gated bash. |

Switch in the REPL with `/plan` and `/build`. One-shot: `kite run --mode plan "…"`.

Approval modes (Codex-style, always visible in the prompt): `auto` · `approve` · `readonly`.

---

## 1. Component / state diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  STREAM PANE  (scrollback, single column)                        │
│                                                                  │
│  you ─┐                                                          │
│       └─ task text                                               │
│                                                                  │
│  plan                                                            │
│    ✓ inspect auth                                                │
│    ● add tests          ← live; rewritten on todo_write          │
│    ○ run pytest                                                  │
│                                                                  │
│  groq/llama-3.3-70b                                              │
│  streamed tokens…                                                │
│                                                                  │
│  ▸ grep  pattern=login                                           │
│      line1                                                       │
│      …  ▸ +12 lines  /expand                                     │
│  ✓ grep                                                          │
│                                                                  │
│  ▸ edit  path=src/auth.py                                        │
│  ⚠  approve edit                                                 │
│      --- a/src/auth.py                                           │
│      +++ b/src/auth.py                                           │
│      @@ -10,3 +10,6 @@                                           │
│      -old                                                        │
│      +new                                                        │
│      [a] once  [s] session  [p] always  [n] deny  [q] stop       │
│  ✓ edit                                                          │
│      +  added line                                               │
│      -  removed line                                             │
│                                                                  │
│  result · Submitted                                              │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  STATUS FOOTER / PROMPT                                          │
│  kite · build · approve · groq/llama · ctx 12% · $0.021 · main   │
│  ❯  _                                                            │
└──────────────────────────────────────────────────────────────────┘

State
  SessionUiState.mode            plan | build
  SessionUiState.approval        auto | approve | readonly
  SessionUiState.todos[]         pending | in_progress | completed
  SessionUiState.cost / tokens   running totals
  ApprovalPolicy                 session + ~/.kite/approvals.json
  GitCheckpoints                 one kite: commit per todo/task → /undo
  CommandIndex                   builtins + markdown commands + plugins + skills
  MemoryStore                    ~/.kite/memory + .kite/memory notes

Event loop (core never renders)
  stream_start → stream_delta* → stream_end
       → tool_start → [approval] → tool_end → todo? → commit? → …
       → context → compact? → agent_end | error | interrupt
```

Cold start: the REPL prints chrome and the prompt immediately. Model resolve, KITE.md, and the repo map load on the first task — not before the prompt is interactive.

---

## 2. Style guide

See `src/kite/ui/style.py` (source of truth).

**Palette**

| Token | Color | Use |
|-------|--------|-----|
| brand | cyan | product name, prompt |
| assistant | magenta | model speech label |
| success | green | applied, done, allow |
| pending | yellow | approval, in-progress |
| error | red | blocked, fail, interrupt |
| muted | dim | collapsed output, meta |

**Symbols (never color alone)**

`✓` success · `✗` fail · `⚠` approval · `●` in-progress · `○` pending · `▸` collapsed · `▾` expanded · `❯` input · `↻` compact

**Spacing**

- 2-space gutter
- Tool output collapsed to 4 lines (`COLLAPSE_LINES`)
- Diffs: first 40 lines, then `▸ +N lines  /expand`
- Footer: one line, `·` separators
- Panels: `padding=(0, 1)`

---

## 3. Render loop

Implemented in `src/kite/ui/render.py` (`RunDisplay.__call__`):

1. `stream_delta` writes tokens to stdout immediately; a spinner starts if nothing arrives for ~1s.
2. `tool_start` prints `▸ tool  key=value  [reason]`. Output is not shown yet.
3. `tool_end` prints `✓/✗/⚠`, then a collapsed body or a colored unified diff (never a full-file reprint).
4. Mutating tools hit `ApprovalPolicy` (`once / session / always this pattern`) with the **exact** command or diff in the panel.
5. `todo_write` rewrites the plan checklist in place (done / in-progress / pending). Completing a todo (or ending the turn) flushes one `kite:` commit of that step's files.
6. Footer updates model, mode, approval, ctx %, cost, git branch.

Slash commands are parsed before any natural-language turn. Builtins (`/plan`, `/build`, `/undo`, `/memory`, …) never hit the model. Skills (`/commit`), bundled prompts (`/explain` `/fix` `/pr`), `.kite/commands/*.md`, `~/.kite/commands/*.md`, and plugin commands expand into the turn. `/commands new name` and `/plugins init name` scaffold files. `/remember` writes the durable memory store.

Interrupt: **Ctrl+C** stops the current turn without killing the process; type a correction and continue. `/undo` resets the last `kite:` task commit.

---

## 4. Anti-patterns we refuse

- Silent commands with no spinner after ~1s
- Applying edits without showing a unified diff first
- Burying "what changed" under a huge log
- Mixing conversational text and raw tool dumps unstyled
- Approval prompts that truncate or vague-out the command

---

## 5. How to run

```
kite                         # REPL; prompt is interactive before context loads
kite chat --mode plan
kite run --mode build --approval approve "add tests"
```

PDFs are generated from this file and `kite-system-design.md`:

```
uv pip install fpdf2
python scripts/build_design_pdf.py
```
