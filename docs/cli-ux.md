# Kite CLI UX

**Agent:** kite
**Version:** 0.8.0
**Language:** Python · Rich + prompt_toolkit (single-column, not a full-screen TUI)
**Companion:** [kite-system-design.md](kite-system-design.md) (architecture, atlas, tradeoffs)

Optimize for **trust, legibility, and speed of comprehension**. The user should always know what the agent is doing and why, and be able to stop or steer it in under a second.

Patterns we took, not invented:

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

Approval modes (Codex-style, always visible in the prompt): `auto` · `approve` · `trust` · `readonly`.

**Sandbox:** off by default (**host** mode). `/restricted on` clamps file/bash paths to the session cwd; footer shows `restricted` when active.

**Slash menu:** scroll the `/` completion dropdown with the mouse wheel (or ↑/↓ when the menu is open). Long lists show a scrollbar.

Effort (Antigravity `/effort`, Codex thinking): `/thinking` `/fast` `/reasoning auto|off|fast|thinking`. Shown on the footer when not `auto`.

**Keyboard shortcuts** (composer): `Ctrl+O` toggle tool output expand · `Ctrl+P` plan · `Ctrl+B` build · `Ctrl+S` flash status on footer · `Ctrl+C` stop turn · `Tab` slash menu.

**Loaders** (beautifului-inspired, TTY-only): default pixel-grid loader with shimmer label and elapsed time. Override with `KITE_LOADER=grid|dots|orbit|wave|spin`.

**Tool cards:** `▸ read  src/foo.py  …` while running (reason on the next line when provided); parallel read-only batches show `parallel N read-only tools` once. `✓ edit  1.2s  +2,-1` when done, with a muted one-line summary for reads (`42 lines  ·  preview…`). **Task rows** show `Running` / `Completed` / `To do` badges.

**Stream coalescing:** small `stream_delta` / reasoning chunks batch before Rich writes — less flicker on fast models.

**Context meter** on footer: `ctx ████░░░░ 50%`. `/expand` toggles full tool output; `/collapse` resets.

---

## 1. Component / state diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  STREAM PANE  (scrollback, single column, history cells)          │
│                                                                  │
│  ›  task text                                                    │
│                                                                  │
│  plan                                                            │
│    ✓ inspect auth                                                │
│    ● add tests          ← live; rewritten on todo_write          │
│    ○ run pytest                                                  │
│                                                                  │
│  …  thinking (italic dim, never mixed into the answer)           │
│  •  the actual reply                                             │
│                                                                  │
│  ▸ grep  pattern=login                                            │
│      line1                                                       │
│      …  ▸ +12 lines  /expand                                     │
│  ✓ grep                                                          │
│                                                                  │
│  ▸ edit  path=src/auth.py                                        │
│  ⚠  approve edit                                                 │
│      src/auth.py  +125,-21  +++++++++++++++++++++-----               │
│      --- a/src/auth.py                                           │
│      +++ b/src/auth.py                                           │
│      [a] once  [s] session  [p] always  [n] deny  [q] stop       │
│  ✓ edit  +125,-21                                                │
│                                                                  │
│  ↻  48 → 12              ← compaction boundary
  ◇  auto pre-compact     ← context checkpoint (full transcript saved)
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
  GitCheckpoints                 one kite: commit per todo/task -> /undo
  CommandIndex                   builtins + markdown commands + plugins + skills
  MemoryStore                    MEMORY.md (semantic) + episodes.sqlite (episodic)

Event loop (core never renders)
  stream_start → stream_reasoning* → stream_delta* → stream_end
       → tool_start → [approval] → tool_end → todo? → commit? → …
       → context → compact? → agent_end | error | interrupt
```

Cold start: the REPL prints chrome and the prompt immediately. Model resolve, `KITE.md`, and the repo map load on the first task, not before the prompt is interactive.

**Sandbox.** File tools and bash `cwd` are locked to the project workspace. Absolute paths that leave it, system directories, SSH keys, `.env`, and `.git/hooks|config` are blocked. User-initiated `/attach` / `/clip` can still read files from anywhere, the agent cannot.

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

Thinking and answer never share a block. The model id is not reprinted as a speech label, it lives on the footer.

**Palette**

| Token | Color | Use |
|-------|--------|-----|
| brand | cyan | product name, composer |
| thinking | italic dim | internal chain-of-thought |
| success | green | applied, done, allow |
| pending | yellow | approval, in-progress, effort badge |
| error | red | blocked, fail, interrupt |
| muted | dim | collapsed output, meta |
| kite.diff.add | green | insertions, `+125` |
| kite.diff.del | red | deletions, `-21` |

**Symbols (never color alone)**

`✓` success · `✗` fail · `⚠` approval · `●` in-progress · `○` pending · `▸` tool · `›` you · `•` answer · `…` thinking · `↻` compact · `◇` checkpoint

**Spacing**

- 2-space gutter; subsequent lines of a cell align under the glyph
- Tool output collapsed to 4 lines (`COLLAPSE_LINES`); `/expand` toggles, `/collapse` resets
- Diffs: `+125,-21` (green/red) then a `++++----` bar, then the first 40 hunk lines (`▸ +N lines  /expand`)
- Footer: one line, `·` separators, includes effort when not `auto`
- No panels around you / result / help

---

## 3. Render loop

Implemented in `src/kite/ui/render.py` (`RunDisplay.__call__`):

1. Spinner says **thinking** until tokens arrive (~1s). Tool calls switch it to **working**.
2. `stream_reasoning` writes the `…` cell (italic dim). `stream_delta` writes the `•` cell (normal). They never mix.
3. `tool_start` prints `▸ tool  key=value  [reason]`. Output is not shown yet.
4. `tool_end` prints `✓/✗/⚠` plus git-stat `+125,-21` (green/red) on write/edit, then a collapsed body or a colored unified diff (never a full-file reprint).
5. Mutating tools hit `ApprovalPolicy` (`once / session / always this pattern`) with the **exact** command or diff, compact, not a rainbow panel.
6. `todo_write` rewrites the plan checklist in place. Completing a todo (or ending the turn) flushes one `kite:` commit of that step's files.
7. Compaction prints `↻  before → after` as a boundary. Auto-checkpoint at ~72% context prints `◇ checkpoint` with id.
8. Footer updates model, mode, approval, effort, ctx %, cost, git branch.

Slash commands are parsed before any natural-language turn. Builtins (`/plan`, `/build`, `/checkpoint`, `/handoff`, `/compact`, `/select`, `/thinking`, `/fast`, `/undo`, `/memory`, `/effort`, …) never hit the model. Skills (`/commit`), bundled prompts (`/explain` `/fix` `/pr`), `.kite/commands/*.md`, `~/.kite/commands/*.md`, and plugin commands expand into the turn. Full map: [kite_commands.md](../kite_commands.md). Type `/` for the dropdown (name + one-line description).

Interrupt: **Ctrl+C** requests end-to-end interrupt (model stream + long bash) without killing the REPL; type a correction and continue. `/undo` resets the last `kite:` **git** task commit. `/checkpoint restore` rewinds the **transcript** without touching git.

---

## 4. Anti-patterns we refuse

- Silent commands with no spinner after ~1s
- Mixing thinking tokens into the answer cell
- Shouting `REASONING` / `ANSWER` labels or boxing the user turn
- Applying edits without a unified diff and `+N,-M` counts first
- Burying "what changed" under a huge log
- Approval prompts that truncate or vague-out the command

---

## 5. How to run

### Install (any workstation)

From the repo (or after cloning):

```bash
git clone https://github.com/KhanUzeb/kite.git && cd kite
./scripts/install.sh          # macOS/Linux
# .\scripts\install.ps1         # Windows PowerShell
```

One-liner (installs to `~/kite` or `%USERPROFILE%\kite`):

```bash
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
```

Manual: `uv venv --python 3.12` → activate → `uv pip install -e ".[dev]"`. Then `kite setup` (recommended) or `kite providers` + `kite models --select`. Full options: [README.md](../README.md#setup).

### Tests & CI

```bash
pytest
```

GitHub Actions (`.github/workflows/tests.yml`) runs `pytest` on every push and pull request to `main` (Python 3.11 + 3.12). Use **Actions → Tests → Run workflow** to re-run manually. See [CONTRIBUTING.md](../CONTRIBUTING.md#ci-github-actions).

### Workspace (any project directory)

Install once. Activate the venv (or add `.venv/bin` / `.venv\Scripts` to `PATH`). Then `cd` into any repo, Kite treats **current directory** as the workspace (tools, git, `.kite/` overlays, `AGENTS.md`).

```bash
cd ~/projects/my-app
kite
kite run "add tests"
```

Or pass `--cwd` without changing shell directory:

```bash
kite run --cwd ~/projects/my-app "review auth"
kite chat --cwd /path/to/other-repo
```

Global state: `~/.kite/` (sessions, config, skills). Per-repo overlays: `<repo>/.kite/commands`, `plugins`, `memory`.

### Session

```
kite                         # REPL; prompt is interactive before context loads
kite chat --mode plan
kite run --mode build --approval approve "add tests"
```

### PDFs

PDFs are generated from this file and `kite-system-design.md`:

```
uv pip install fpdf2
python scripts/build_design_pdf.py
```
