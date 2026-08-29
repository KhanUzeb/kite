# Kite CLI UX

**Agent:** kite  
**Version:** 0.5.0  
**Language:** Python · Rich + prompt_toolkit (single-column, not a full-screen TUI)  
**Companion:** [kite-system-design.md](kite-system-design.md) (architecture, atlas, tradeoffs)

Optimize for **trust, legibility, and speed of comprehension**. The user should always know what the agent is doing, why, and be able to stop or steer it in under a second.

Patterns stolen, not invented:

| Harness | What we took |
|---------|----------------|
| Codex CLI | History cells: `›` you, `…` thinking (italic dim), `•` answer. Status words **thinking** / **working**. Approval in the prompt line, not a boxed result. Composer `›` at the bottom. |
| Antigravity CLI | **effort** badge (`fast` / `thinking`) on the footer; compaction as a boundary marker; tools as one-line rows; keyboard-first, no flicker. `/effort` for depth vs latency. |
| Claude Code | Collapsible tool blocks; live todo list; unified diffs; exact-command permission prompts; `KITE.md` project memory |
| Aider | Git commit per todo/task; `/undo`; running cost in the status line |
| Gemini CLI / opencode | Single-column, keyboard-first, theme-aware (`ansi_dark` / `ansi_light`), lazy context after the prompt is live |

## Modes

| Mode | Tools | Approval default | What it produces |
|------|--------|------------------|------------------|
| **plan** | read, grep, glob, ls, task, webfetch, websearch, webcrawl, skill, memory, todo_* | `readonly` | A live checklist. No file mutations. |
| **build** | all tools | `approve` (chat) / `auto` (one-shot `kite run`) | Diffs, git checkpoints, gated bash. |

Switch in the REPL with `/plan` and `/build`. One-shot: `kite run --mode plan "…"`.

Approval modes (Codex-style, always visible in the prompt): `auto` · `approve` · `readonly`.

Effort (Antigravity `/effort`, Codex thinking): `/thinking` `/fast` `/reasoning auto|off|fast|thinking`. Shown on the footer when not `auto`.

---

## 1. Component / state diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  STREAM PANE  (scrollback, single column — history cells)          │
│                                                                  │
│  ›  task text                                                    │
│                                                                  │
│  plan                                                            │
│    ✓ inspect auth                                                │
│    ● add tests          ← live; rewritten on todo_write          │
│    ○ run pytest                                                  │
│                                                                  │
│  …  thinking (italic dim — never mixed into the answer)           │
│  •  the actual reply                                             │
│                                                                  │
│  ▸ grep  pattern=login                                            │
│      line1                                                       │
│      …  ▸ +12 lines  /expand                                     │
│  ✓ grep                                                          │
│                                                                  │
│  ▸ edit  path=src/auth.py                                        │
│  ⚠  approve edit                                                 │
│      --- a/src/auth.py                                           │
│      +++ b/src/auth.py                                           │
│      [a] once  [s] session  [p] always  [n] deny  [q] stop       │
│  ✓ edit                                                          │
│                                                                  │
│  ↻  48 → 12              ← compaction boundary                      │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  STATUS FOOTER / COMPOSER                                        │
│  kite · build · approve · groq/llama · thinking · ctx 12% · $  │
│  ›  _                                                            │
└──────────────────────────────────────────────────────────────────┘

State
  SessionUiState.mode            plan | build
  SessionUiState.approval        auto | approve | readonly
  SessionUiState.reasoning       auto | off | fast | thinking
  SessionUiState.todos[]         pending | in_progress | completed
  SessionUiState.cost / tokens   running totals
  ApprovalPolicy                 session + ~/.kite/approvals.json
  GitCheckpoints                 one kite: commit per todo/task → /undo
  CommandIndex                   builtins + markdown commands + plugins + skills
  MemoryStore                    MEMORY.md (semantic) + episodes.sqlite (episodic)

Event loop (core never renders)
  stream_start → stream_reasoning* → stream_delta* → stream_end
       → tool_start → [approval] → tool_end → todo? → commit? → …
       → context → compact? → agent_end | error | interrupt
```

Cold start: the REPL prints chrome and the prompt immediately. Model resolve, KITE.md, and the repo map load on the first task — not before the prompt is interactive.

**Sandbox.** File tools and bash `cwd` are locked to the project workspace. Absolute paths that leave it, system directories, SSH keys, `.env`, and `.git/hooks|config` are blocked. User-initiated `/attach` / `/clip` can still read files from anywhere — the agent cannot.

**Attach.** `/attach path`, `/clip`, or `@file.png` in the prompt. Images are sent as `image_url` parts and **routed to a live multimodal model** on the current provider, or another selected provider that has a key, if the current model cannot see.

---

## 2. Style guide

See `src/kite/ui/style.py` (source of truth).

**Cells (Codex)**

| Glyph | Channel | Style |
|-------|---------|-------|
| `›` | you / composer | muted glyph, default text |
| `…` | thinking | italic dim |
| `•` | answer | default |
| `▸` | tool start | cyan row |
| `⚠` | approve | yellow, no box |

Thinking and answer never share a block. The model id is not reprinted as a speech label — it lives on the footer.

**Palette**

| Token | Color | Use |
|-------|--------|-----|
| brand | cyan | product name, composer |
| thinking | italic dim | internal chain-of-thought |
| success | green | applied, done, allow |
| pending | yellow | approval, in-progress, effort badge |
| error | red | blocked, fail, interrupt |
| muted | dim | collapsed output, meta |

**Symbols (never color alone)**

`✓` success · `✗` fail · `⚠` approval · `●` in-progress · `○` pending · `▸` tool · `›` you · `•` answer · `…` thinking · `↻` compact

**Spacing**

- 2-space gutter; subsequent lines of a cell align under the glyph
- Tool output collapsed to 4 lines (`COLLAPSE_LINES`)
- Diffs: first 40 lines, then `▸ +N lines  /expand`
- Footer: one line, `·` separators, includes effort when not `auto`
- No panels around you / result / help

---

## 3. Render loop

Implemented in `src/kite/ui/render.py` (`RunDisplay.__call__`):

1. Spinner says **thinking** until tokens arrive (~1s). Tool calls switch it to **working**.
2. `stream_reasoning` writes the `…` cell (italic dim). `stream_delta` writes the `•` cell (normal). They never mix.
3. `tool_start` prints `▸ tool  key=value  [reason]`. Output is not shown yet.
4. `tool_end` prints `✓/✗/⚠`, then a collapsed body or a colored unified diff (never a full-file reprint).
5. Mutating tools hit `ApprovalPolicy` (`once / session / always this pattern`) with the **exact** command or diff — compact, not a rainbow panel.
6. `todo_write` rewrites the plan checklist in place. Completing a todo (or ending the turn) flushes one `kite:` commit of that step's files.
7. Compaction prints `↻  before → after` as a boundary, then continues.
8. Footer updates model, mode, approval, effort, ctx %, cost, git branch.

Slash commands are parsed before any natural-language turn. Builtins (`/plan`, `/build`, `/undo`, `/memory`, `/effort`, …) never hit the model. Skills (`/commit`), bundled prompts (`/explain` `/fix` `/pr`), `.kite/commands/*.md`, `~/.kite/commands/*.md`, and plugin commands expand into the turn. Full map: [kite_commands.md](../kite_commands.md). Type `/` for the dropdown (name + one-line description).

Interrupt: **Ctrl+C** stops the current turn without killing the process; type a correction and continue. `/undo` resets the last `kite:` task commit.

---

## 4. Anti-patterns we refuse

- Silent commands with no spinner after ~1s
- Mixing thinking tokens into the answer cell
- Shouting `REASONING` / `ANSWER` labels or boxing the user turn
- Applying edits without showing a unified diff first
- Burying "what changed" under a huge log
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
