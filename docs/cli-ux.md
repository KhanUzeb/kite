# Kite CLI UX

**Agent:** kite
**Version:** 0.9.2
**Language:** Python · Rich + prompt_toolkit (single-column, not a full-screen TUI)
**Companion:** [kite-system-design.md](kite-system-design.md) (architecture, atlas, tradeoffs)

Keep the session readable: the user should always know what the agent is doing and why, and be able to stop or steer it quickly.

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
| **plan** | read/grep/glob/ls, inspection `bash`, `task`/`subagent`, web/Context7, skill, memory, `todo_*` | `readonly` | A live checklist + risks/open questions. No file mutations; no submit-as-done. |
| **build** | all tools | `approve` (chat) / `auto` (one-shot `kite run`) | Diffs, git checkpoints, gated bash. Executes the plan checklist if one exists. |

Switch in the REPL with `/plan` and `/build` (also Ctrl+P / Ctrl+B, F3 / F4). One-shot: `kite run --mode plan "…"`.

**Plan → build:** `/plan` explores and writes the checklist; `/build` keeps that list and applies it. Footer shows `plan · readonly` (and `list done/total` when a checklist is present).

Approval modes (Codex-style, always visible in the prompt): `auto` · `approve` · `trust` · `readonly` · `yolo`.

**Mandatory approval:** high-risk actions always prompt, regardless of approval mode (including `yolo`), workspace location, or remembered patterns. No session/always shortcut on these prompts: only **once**, **deny**, or **stop**:

| Category | Examples |
|----------|----------|
| Git history | `git commit`, `git push`, `git reset`, `git rebase`, `git clean` |
| Destructive | `rm`, `rmdir`, `del`, `Remove-Item` |
| Privileged | `sudo`, `su`, `doas` |
| Package installs | `pip install`, `npm install`, `cargo install`, `brew install`, … |
| Permissions | `chmod`, `chown`, `icacls`, `takeown` |
| Network fetch | `curl`, `wget`, `Invoke-WebRequest` |
| Remote / containers | `ssh`, `scp`, `docker run`, `kubectl apply` |
| Outside workspace | any `bash` whose cwd escapes the project root |
| Outside workspace writes | `write` / `edit` to paths outside the project |

Regular in-workspace `write`/`edit` and safe bash (`git status`, `pytest`, `rg`) still follow the active approval mode.

**Sandbox:** off by default (**host** mode). `/restricted on` clamps file/bash paths to the session cwd; footer shows `restricted` when active. Restricted mode may still **read** `~/.kite/skills` (including symlink/junction targets) so skill packs can load extra files; writes there stay blocked.

**Slash menu:** `Tab` cycles completions for `/` commands and `@path` attach tokens. `Enter` always sends the line (it does not accept a hidden completion). Use ↑/↓ when the menu is open. Mouse wheel scrolling of the `/` dropdown needs `KITE_MOUSE=1` (that captures the mouse and disables native drag-select).

**Attach in composer:** type `@src/foo.py` (word-boundary `@`; `user@example.com` is not completed). Same paths as `/attach`.

**Copy / paste:** Mouse capture is **off** by default so the terminal keeps drag-select, copy, and right-click paste. In the composer: `Ctrl+V` / `Shift+Insert` paste from the OS clipboard; `Ctrl+Insert` copies the composer selection. Set `KITE_MOUSE=1` only if you want wheel-scroll on the slash menu (then use Shift+drag in most terminals to select text).

Effort (Antigravity `/effort`, Codex thinking): `/thinking` `/fast` `/reasoning auto|off|fast|thinking`. Shown on the footer when not `auto`.

**Keyboard shortcuts** (composer, `eager` so they beat emacs readline):

| Key | Action |
|-----|--------|
| `Esc` / `Ctrl+C` | **Stop** the running turn (session stays). Idle `Ctrl+C` clears the line; it does not quit. |
| `Ctrl+G` | **Steer:** stop and send the composer text as the next turn. Idle: no-op. |
| `Enter` | Send the line. While working: **queue** a follow-up (slash commands wait until the turn ends) |
| `Ctrl+V` / `Shift+Insert` | Paste OS clipboard into the composer |
| `Ctrl+Insert` | Copy composer selection to OS clipboard |
| `Ctrl+O` / `F6` | Toggle tool output expand |
| `Ctrl+T` / `F7` | Toggle thinking trace (expanded by default) |
| `Ctrl+P` / `F3` | Plan mode |
| `Ctrl+B` / `F4` | Build mode |
| `F2` | Flash status on footer (`Ctrl+S` is not bound; terminals use it for XOFF) |
| `F5` | Refresh live models from the API, then pick |
| `Ctrl+D` / `/quit` | Close the REPL |
| `Tab` | Cycle slash / `@` completions (`Enter` always submits) |

While a turn is running the composer stays pinned (placeholder: `add a follow-up while Kite works…`). **Enter** queues a follow-up without tearing down the input box; **Esc** stops; **Ctrl+G** steers. `/tasks` lists the running command and the queue. The footer shows a running line (`[HH:MM:SS] command  running`) plus metrics: **tok/s**, **cache hit %**, context meter, and cost. After stop, keep typing in the **same session** until `/quit` or `Ctrl+D`.

**Loaders** (beautifului-inspired, TTY-only): default pixel-grid loader with shimmer label and elapsed time. Override with `KITE_LOADER=grid|dots|orbit|wave|spin`.

**Tool cards:** `▸ read  src/foo.py  …` while running (reason on the next line when provided); parallel read-only batches show `parallel N read-only tools` once. `✓ edit  1.2s  +2,-1` when done, with a muted one-line summary for reads (`42 lines  ·  preview…`). **Task rows** show `Running` / `Completed` / `To do` badges with a coloured progress bar (`Tasks 2/5 ████░░`). Active item highlighted in cyan; done in green.

**Provider retry:** transient network/rate-limit errors auto-retry with backoff (config: `provider_max_retries`). Session is preserved; send another message or `kite resume <id>` to continue.

**Budget pause:** hitting `step_limit` / `cost_limit` (or wall-clock) ends the turn as a soft pause (`LimitsExceeded` / `TimeExceeded`), not a crash. Interactive chat defaults to ~80 steps / $10 when still on package defaults (40 / $5); explicit lower user caps are honored. If unfinished work remains (open todos), Kite may **auto-continue up to 2 times** with a continuity brief (`budget continue N/2 — resuming…`), then soft-pause. Session is kept; queued inbox messages win over silent auto-continue. Use `/compact` if context is full.

**Working-state continuity (Codex/Pi-style):** after compact or before a budget continue, Kite stores a short brief (mission / done / next / todos) and injects it as **working continuity** — not durable memory. Use `/remember` or `/memory` when you want MEMORY.md / episodic notes in the prompt.

**Durable memory:** MEMORY.md and episodic sqlite are **opt-in** per session (`/remember`, `/memory`, or the `memory` tool). Default runs do not inject them unless `[memory] inject = "always"` in runtime config.

**Completion discipline:** build mode finishes with the **`submit`** tool (`message` with Done / Changed / Verification) or legacy `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` in bash (or a short casual chat like "hi" with no edits). Prose-only "I'm done" after file changes is blocked (`submit_blocked` event). Footer shows live **`verification_status`** (e.g. `unverified edits`) during the run; urgent states also flash briefly (~8s). After 2 idle no-tool turns the run stalls — **except** when verification is `changed_unverified`, in which case Kite nudges with a suggested check command instead of stalling. Waiting on an approval prompt is not an idle turn. While approval is pending, the toolbar shows **`[a] once · [n] deny · [q] stop`** (session/always keys when not mandatory) — not queue/steer hints. Successful submit shows **work complete**; partial verification shows a warning banner.

**Cost warnings:** at ~80% of the turn budget, a warning appears on the footer flash while the composer is pinned (no mid-turn scrollprint).

**Windows bash:** Kite runs commands through the shell (`powershell` on Windows, `bash` elsewhere). Prefer `Remove-Item` / `rmdir` for cache dirs under the workspace (`.pytest_cache`, `.ruff_cache`); these are allowed in auto/yolo without mandatory approval. Avoid Unix-only pipes like `| head` when `rg`/`read`/`glob` work.

**Fatal errors:** unexpected exceptions stop the run with `exit_status=Error`, print the message + traceback tail, and save `/trace` in the REPL. No silent re-raise.

**BYOS login** (`kite login chatgpt|claude|grok` or `/login`): after you pick a subscription provider, Kite opens your browser and shows a left-bar panel. ChatGPT uses a device code you type on the page; Grok completes in the browser callback; Claude imports Claude Code or accepts a pasted `claude setup-token`. Waiting line until you finish or Ctrl+C.

**Numbered pickers** (TTY): empty `/approve`, `/theme`, `/font`, `/reasoning`, `/restricted`, `/resume`, `/sessions`, `/logout`, `/skills` open a left-bar numbered list (type a number, id, or empty to cancel). The same picker is used by `kite sessions`, `kite resume`, `kite models`, `kite providers`, `kite keys`, and `kite skills` when stdin is a terminal. Piped/CI runs still dump tables (`kite models --list`). `kite run` with no task asks **Task:** instead of exiting. Interactive prompts stay in the left bar; there is no right-hand sidebar.

**Background jobs:** one `JobRegistry` per session tracks bash started with `background=true` and live `subagent` workers. Footer shows `jobs N`. `/jobs` lists active jobs (left-bar pick to kill). `/kill id` or `/kill all` stops them. Quitting the REPL (`/quit`, Ctrl+D) kills remaining jobs.

**Parallel helpers:** `task` fans out cheap search-style prompts (no nested LLM). `subagent` runs bounded nested agent turns and registers each worker in the same job registry. Stream rows: `▸ subagent` / `✓ subagent` (and job start/end events for background bash).

**Busy chrome:** while a turn runs, the composer stays pinned at the bottom (placeholder: `add a follow-up while Kite works…`). Thinking/working activity updates the **toolbar running line** (animated glyph + label) — not a separate stderr spinner that would overwrite the input. Esc / Ctrl+C / `/stop` cancels; Ctrl+G / `/steer …` injects a correction; Enter queues chat follow-ups. SIGINT handling for the agent loop stays on the main thread.

---

**Context meter** on footer: `ctx ████░░░░ 50%`. `/expand` toggles full tool output; `/collapse` resets. Thinking traces stream **expanded by default**; `/expand-thinking collapse` or `Ctrl+T` collapses to a summary. Double-click the composer (or `Ctrl+T` / `/expand-thinking`) to expand again.

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
| brand | bold cyan | product name, composer, `/` menu |
| thinking | italic muted | internal chain-of-thought |
| success | bright green | applied, done, allow |
| pending | bright yellow | approval, in-progress, effort badge |
| error | bright red | blocked, fail, interrupt |
| muted | `#6e6e6e` | collapsed output, meta |
| kite.diff.add | bright green | insertions, `+125`, `+` lines |
| kite.diff.del | bright red | deletions, `-21`, `-` lines |
| kite.diff.hunk | bright cyan | `@@` hunk headers |
| kite.diff.ctx | muted grey | unchanged context lines |

Dark themes use a near-black `/` completion menu (`#050505`) with cyan slash labels. `/theme dark` deepens muted greys further.

**Symbols (never color alone)**

`✓` success · `✗` fail · `⚠` approval · `●` in-progress · `○` pending · `▸` tool · `›` you · `•` answer · `…` thinking · `↻` compact · `◇` checkpoint

**Spacing**

- 2-space gutter; subsequent lines of a cell align under the glyph
- Tool output collapsed to 4 lines (`COLLAPSE_LINES`); `/expand` toggles, `/collapse` resets
- Diffs: `+125,-21` (bright green/red) then a `++++----` bar, then colour-coded hunk lines (`+` green, `-` red, `@@` cyan, context muted). First 40 lines by default (`▸ +N lines  /expand`)
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

Interrupt: **Esc** or **Ctrl+C** stops the current turn (model stream + bash) without killing the REPL. **Ctrl+G** steers: stop and send the composer text as the next turn. **Enter** while working queues a follow-up. Type another message in the **same session** until `/quit` or `Ctrl+D`. `/undo` resets the last `kite:` **git** task commit. `/checkpoint restore` rewinds the **transcript** without touching git.

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
