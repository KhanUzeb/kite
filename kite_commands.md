# Kite commands

Kite is a coding agent. **What lands in git is still yours.** These commands steer the process, not a second commit stream.

**New to Kite?** Start with the visual [guide.md](guide.md) (workflows, example Q&A, cockpit layout). This file is the complete reference.

There are four surfaces:

| Surface | When | Hits the model? |
|---------|------|-----------------|
| **CLI** (`kite …`) | Outside a session, or to start one | Only `run` / `chat` / `resume` |
| **REPL slash** (`/…`) | Inside `kite` / `kite chat` | Control slashes never. Prompt slashes expand into the next turn. |
| **Markdown commands / skills / plugins** | `/explain`, `/commit`, `/skill debug`, plugin `/hello` | Yes, they become the user task |
| **Agent tools** | During a turn (`read`, `edit`, `bash`, …) | Yes, the model calls them |

**Install & workspace:** one-time setup via `scripts/install.sh` / `install.ps1` (see [§6](#6-install--development)). After that, run `kite` from any project directory; workspace defaults to shell cwd, or set `--cwd`.

Prefix `//` if you need a natural-language line that starts with `/`.

---

## 1. CLI

```
kite                         # REPL (same as kite chat)
kite --version
kite chat [--mode plan|build] [--approval auto|approve|trust|readonly] [--session id]
kite run "task"              # one-shot
kite resume <session-id>                 # open that transcript in chat
kite resume <session-id> [follow-up]     # one-shot continue
kite resume --last [--retry]             # newest session for cwd; --retry sends recovery follow-up
kite resume abc12345                     # id prefix works when unique
kite sessions                            # table: date, time, title, model, status, id
kite sessions humanize                   # filter by title, cwd, date, or id prefix
kite sessions -q docs                    # same filter flag
kite sessions --no-pick                  # print table only (no picker)
kite sessions --show <id> [--tail N]     # meta + transcript tail + resume hint
```

Shared flags on `run` / `chat` / `resume`:

| Flag | Meaning |
|------|---------|
| `-p` / `--provider` | Catalog name (`openai`, `anthropic`, `zen`, `go`, `nvidia`, …) |
| `-m` / `--model` | Model id within that provider |
| `--cwd` | Workspace |
| `--config` | Runtime TOML name or path |
| `--mode plan\|build` | Read-only checklist vs apply edits |
| `--approval yolo\|auto\|supervised\|approve\|trust\|readonly` | `yolo` = no prompts; `auto`/`trust` = workspace-scoped; `supervised`/`approve` = approve mutations; `readonly` = block writes |
| `--steps` `--cost` `--time` | Limits (honored by `run`, `chat`, and one-shot `resume`) |
| `--long` | Long-task mode: higher step/cost limits, phased checkpoints, long-task prompt |
| `--no-context` `--no-compact` `--no-guardrails` | Opt out of injection, compaction, sandbox |
| `--attach PATH` | Attach a file or image (repeatable). Images route to a live vision model. Missing paths exit 2 before the REPL starts. |
| `--role` | `auto` / `architect` / `implementer` / `debugger` |
| `-v` | Verbose tool bodies |

One-shot / headless flags (`kite run`, `kite resume <id> "continue"` — not `kite chat`):

| Flag | Meaning |
|------|---------|
| `-q` | Quiet |
| `--headless` | Line-oriented stderr log (`[tool]`, `[crew]`, `[out]`), no TTY prompts — CI / cloud agents |
| `--no-stream` | With `--headless`, hide live bash/tool output lines |
| `--json` `-o PATH` `--label` | Machine output / trajectory path / session label |

Persistent compaction is `kite config --auto-compact true|false` (not a run/chat flag).

`--headless` also activates when stdout is not a TTY or with `-q`. Approval policy is never weakened: `readonly` blocks mutations, `approve` denies mutations when no prompt is available, and `auto` permits ordinary in-workspace changes while mandatory approval gates fail closed.

**Tool philosophy:** inspect with **bash** (`rg`, `head`, `sed -n`, `wc -l`) for token-efficient peeks; use `read` only for bounded slices; `set_cwd` when the user names another directory.

Housekeeping (no model):

```
kite sessions                  # TTY: table then pick → resume / show / delete
kite sessions [query]          # filter by title, cwd, date, or id prefix
kite sessions -q text          # same as positional filter
kite sessions [--limit N] [--show id] [--tail N] [--no-pick]
kite sessions --delete <id> [<id> ...]
kite sessions --delete-all     # TTY confirms; else pass -y
kite setup [-p provider]       # first-run wizard: credentials + model
kite login [provider]          # pick provider if omitted → BYOK key or BYOS browser → pick model
kite logout [provider]         # unlink BYOS subscription (codex, claude, grok/xai)
kite keys                      # TTY: status then pick a provider to link
kite keys [--set [provider]]   # paste BYOK API keys (hidden); also tavily|exa|firecrawl
kite web-keys                  # show optional web tool key status (Tavily / Exa / Firecrawl)
kite web-keys set [name]       # paste web tool key (hidden) → ~/.kite/.env owner-only
kite web-keys logout [name]    # remove a web tool key
kite keys --logout [provider]  # unlink BYOK keys, web keys, or BYOS (omit provider to pick)
kite providers                 # status; TTY then pick to connect
kite models [-p provider]      # TTY: pick a live model (saved). --list dumps the table
kite models --refresh          # bypass cache; re-fetch from the provider API
kite models --select           # same picker
kite config [--set-provider …] [--set-model …] [--select-model] [--set-api-base …]
              [--session-persistence full|redacted|disabled]
kite privacy [--session-persistence full|redacted|disabled]   # security policy summary
kite context [--json]
kite skills                    # TTY: pick a skill to show (trust/origin column)
kite skills [--show name] [--add pkg|path]
kite commands
kite plugins
kite memory [--remember text] [--forget query] [--project]
kite runtime-config [--config name]
kite bench [--json] [--save PATH] [--compare BASELINE.json] [--check] [--ab] [--stress]
kite tasks init [--force] [path]              # write example ~/.kite/tasks/example.jsonl
kite tasks run <file.jsonl> [--stdin] [--json] [--dry-run] [--continue-on-error]
                           [--steps N] [--cost USD] [--time SEC] [-p] [-m]
kite subagents [--show id] [--init id] [--role architect] [--force]
kite dashboard [--session id] [--json] [--watch SEC] [--limit N]
```

### Harness timing (`kite bench`)

Repeatable micro-benchmarks for the **harness only** — no live LLM calls. Use before/after refactors to catch startup, context, and tool regressions.

```bash
kite bench                      # table: name · category · median ms
kite bench --json               # machine-readable report
kite bench --save before.json   # baseline snapshot
kite bench --compare before.json
kite bench --check              # exit 1 if any case exceeds budget (CI gate)
```

| Category | Benchmarks |
|----------|------------|
| **startup** | `cli_import`, `config_load`, `user_config_load`, `catalog_load`, `skills_load`, `repl_chat_init`, `model_resolve`, `slash_index`, `runtime_prepare` |
| **context** | `repo_map`, `prompt_cache_prepare`, `context_gather`, `prompt_assembly` |
| **tools** | `tool_registry`, `read_tool`, `grep_tool`, `bash_echo`, `subprocess_spawn` |

Optional (not in CI pytest): `kite bench --ab` and `kite bench --stress`.

Budget ceilings live in `src/kite/bench/budgets.py`. `pytest tests/test_bench.py` runs the same suite in CI.

### Headless tasks (`kite tasks`)

Run one or more agent tasks without a TTY — for CI, cron, or cloud agents. Uses the same harness as `kite run --headless` but reads tasks from a file or stdin.

```bash
kite tasks init                              # ~/.kite/tasks/example.jsonl
kite tasks run ~/.kite/tasks/example.jsonl   # run batch
echo '{"task": "pytest -q", "label": "tests"}' | kite tasks run --stdin
kite tasks run tasks.jsonl --dry-run         # list without running
kite tasks run tasks.jsonl --json            # machine-readable summary on stdout
kite tasks run tasks.jsonl --steps 20 --time 120
kite run --headless "fix the failing test"   # single task, stderr event log
kite exec "pytest -q" --json                 # CI: headless + quiet + auto approval
```

**Task file format** — JSONL (one object per line) or plain text (one prompt per line). `#` lines and blanks are skipped.

| Field | Meaning |
|-------|---------|
| `task` / `prompt` / `message` | User prompt (required) |
| `label` / `name` | Short name in logs |
| `cwd` / `workspace` | Per-task workspace (default: `--cwd` or `.`) |
| `mode` | `plan` or `build` |
| `approval` | `auto`, `yolo`, `trust`, `approve`, or `readonly`; headless runs preserve the selected policy |
| `long` / `long_task` | Long-task limits + phased checkpoints |

Stderr tags: `[kite]` lifecycle, `[tool]` tool start/end, `[out]` bash/tool lines (redacted), `[crew]` subagent workers, `[stream]` model deltas (`-v`).

Batch exit code is 0 only when every task `exit_status` is `Submitted` **and** leftover bash/subagent jobs were torn down (count 0). Incomplete, stalled, interrupted, budget-exceeded, provider-faulted, and orphan-job tasks return a non-zero batch exit even when their sessions remain resumable (`kite resume <id>`). JSON still includes `exit_status`, `session_id`, `submission`, and `error` so callers can distinguish retryable interruptions from hard failures. `kite tasks run` requires a file (or `--stdin` / `-`); `--steps` / `--cost` / `--time` apply per task.

### Subagent personas (`kite subagents`)

Bundled personas live in the package; **custom personas** override by id in `~/.kite/subagents/<id>.md` (YAML frontmatter + markdown prompt). Distinct from global `/profile` (`PROFILE.md` for the main agent).

```bash
kite subagents                              # table: id, label, role, trust
kite subagents --show scout                 # full prompt body
kite subagents --init auditor --role debugger --label "Auditor"
```

Dispatch at runtime: `subagent` tool with `profile=<id>` and `prompt=…`. User-authored profiles are wrapped as untrusted content.

`kite dashboard` is per-user: it reads your local `~/.kite/sessions` (or `$KITE_HOME`). Overview: active/failed runs, exit statuses, provider/model usage, tool breakdown, cost, tokens, cache, subagents, and sessions needing attention. `--session <id>` drills into one run (cwd, mode, verification, tool failures, event timeline). `--watch 5` refreshes every 5 seconds.

---

## 2. REPL control slashes

These never go to the model.

| Command | What it does |
|---------|----------------|
| `/plan` `/p` | Read-only: explore + checklist (no edits); switch to `/build` to apply |
| `/build` `/b` | Apply edits; continues existing plan checklist; approval leaves `readonly` → supervised |
| `/approve yolo\|auto\|supervised` | Autonomy. Empty: numbered picker. yolo skips in-workspace prompts; high-risk still asks |
| `/restricted on\|off` `/sandbox` | Path sandbox (default **off**). Empty: pick on/off |
| `/privacy` | Security policy summary; `/privacy sessions` picks full/redacted/disabled |
| `/privacy sessions redacted\|full\|disabled` | Set session JSONL persistence (default **redacted**) |
| `/theme [auto\|kite\|dark\|light\|dim\|mono\|monochrome\|catppuccin\|ember\|forest\|hues\|transparent]` | Color palette. Empty: pick |
| `/font [unicode\|ascii]` | Glyph pack. Empty: pick |
| `/reasoning` `/effort auto\|off\|fast\|thinking` | Set effort. Empty: pick |
| `/model [provider/id]` | Show or set model |
| `/model provider/id --save` | Set model and persist to `~/.kite/config.toml` |
| `/select [provider]` | Pick provider if needed, login if unlinked, then pick a live model (saved) |
| `/models [provider [model]]` | Pick a live model and save to `~/.kite/config.toml`. Empty: pick provider first. Two+ provider names: pick among them |
| `/models refresh [provider]` `/refresh` | Clear the model cache, re-fetch from the provider API, then pick (also **F5**) |
| `/provider [name]` | Empty: same connect flow as `/select`. With a name: set provider |
| `/login [provider]` | Always (re)link credentials, then pick a model. BYOS opens a browser + device code |
| `/logout [provider]` | Unlink; omit provider to pick |
| `/sessions` `/session list` | Numbered picker: open / show / delete |
| `/session open [id]` `/resume [id]` | Continue that chat; omit id to pick |
| `/keys` | Credential status with type (BYOK/BYOS), masked key fingerprint, OAuth link state |
| `/thinking` `/fast` | Effort shortcuts (`/reasoning thinking` / `/reasoning fast`) |
| `/undo` | Revert last **kite:** git checkpoint (agent edits only) |
| `/clear` `/new` | Fresh chat session (memory notes stay) |
| `/compact` | Summarize older turns now; ctx meter updates immediately |
| `/cost` | USD + context |
| `/stop` | Stop the current turn; session stays open |
| `/steer text` | Stop and run `text` as the next turn |
| `/tasks` | Show the running turn and queued follow-ups |
| `/goal [text]` | Persistent long-horizon objective (survives provider errors) |
| `/goal` | View current goal status |
| `/goal pause` / `/goal resume` / `/goal clear` | Pause, reactivate, or remove goal |
| `/goal edit …` | Revise goal text (max 4000 chars) |
| `/jobs` | List background bash jobs and live subagents (pick to kill) |
| `/agents` | Subagent crew board — profile, label, status, prompt; `/kill` to stop |
| `/agents profiles` | List bundled + custom personas (`~/.kite/subagents/*.md`) with trust column |
| `/agents show <id>` | Print one persona (path, role, prompt body) |
| `/agents init <id>` | Scaffold `~/.kite/subagents/<id>.md` (edit, then `profile=<id>`) |
| `/agents reload` | Reload profiles from disk (after manual edits) |
| `/agents <id>` | Shortcut for `/agents show <id>` |
| `/kill [id\|all]` | Kill one background job/subagent, or all. Empty: pick |
| `/session` | Current session id |
| `/session show [id]` | Print a transcript (current if omitted) |
| `/session delete [id\|all]` | Drop this (or another) transcript + trajectory |
| `/init` | Write `KITE.md` if missing |
| `/expand` | Toggle expanded tool output |
| `/cockpit` | Toggle run-centric cockpit layout (`on`/`off`/`refresh`; needs ≥100×30 terminal) |
| `/live` | Stream bash output in real time while tools run |
| `/live agents` | Stream subagent crew tool + shell output with worker prefix |
| `/collapse` | Collapse tool output (default) |
| `/trace` | Last traceback |
| `/skills [name]` | List skills (trust/origin column), or print one. Empty: pick to show. User-home skills show `~` (`~/.kite/skills`, `~/.agents/skills`) |
| `/skills add pkg\|path` | Install npm/npx/GitHub into `~/.kite/skills` (**untrusted** — provenance in `.kite-provenance.json`), or **link** a local skill folder |
| `/commands` | List markdown slash prompts |
| `/commands new name` | Write `.kite/commands/name.md` |
| `/plugins` | List plugins |
| `/plugins init name` | Scaffold `.kite/plugins/name` |
| `/memory [semantic\|episodic]` | Semantic markdown + episodic sqlite |
| `/user [add text]` | Global identity (`~/.kite/memory/USER.md`) — always in prompt when present |
| `/profile [add text]` | Global profile (`~/.kite/memory/PROFILE.md`) — stack, goals, constraints |
| `/working [add text]` | Fluid working rhythm (`~/.kite/memory/WORKING.md`) — soft context, always in mind when present |
| `/semantic` | Show `MEMORY.md` notes |
| `/episodic` | Show sqlite episode log |
| `/remember [user\|project] text` | Append a note |
| `/forget id\|substring` | Drop matching notes |
| `/attach path` | Queue a file or image for the next turn (any path on disk) |
| `/clip` `/paste` `/clipboard` | Attach clipboard text or image (**F8** or **Esc v**) |
| `/detach [name\|all]` | Drop queued attachments |
| `/attachments` | List queued files |
| `/help` `/h` | Command map, keyboard shortcuts, and remaining docs (`kite_commands.md`, `CONTEXT.md`, `architecture.md`, `SECURITY.md`, current `docs/RELEASE-X.Y.Z.md`) |
| `/quit` `/q` `/exit` | Leave the REPL |

Ctrl+C stops the **current turn**, not the process.

### Run cockpit (`/cockpit`)

Kite is **run-centric**: the primary object is a **Run** (goal → plan → tools → changes → verification → result), not a chat scrollback.

| Mode | When | Layout |
|------|------|--------|
| **Compact** | Default; any terminal | Dense transcript, footer meter, collapsed tool output |
| **Cockpit** | `/cockpit` or `Ctrl+Space`; terminal ≥100×30 | Work · Run · Inspect panels: timeline, changes (+/−), verification, crew, composer pills |

```text
/cockpit           toggle compact ↔ cockpit
/cockpit on|off    explicit mode
/cockpit refresh   redraw cockpit without toggling
```

On terminals smaller than 100×30 columns × 30 rows, cockpit stays in compact mode. Both modes read the same event stream — switching does not reset the run.

### Keyboard shortcuts (composer)

| Shortcut | Action |
|----------|--------|
| `Esc` / `Ctrl+C` | Stop the running turn (session stays). Idle `Ctrl+C` clears the line; does not quit |
| `Ctrl+D` / `/quit` | Leave the REPL |
| `Ctrl+V` / `Shift+Insert` | Paste OS clipboard into the composer |
| `F8` / `Esc` then `v` | Attach clipboard to the next turn (same as `/clip`) |
| `Ctrl+Insert` | Copy composer selection to OS clipboard |
| `Ctrl+L` | Clear screen |
| `Ctrl+G` | Steer: stop and send the composer text as the next turn |
| `Ctrl+U` | Dequeue: restore all queued messages into the composer for editing |
| `Enter` | Send the line. While working, queues a chat follow-up |
| `@path` | Inline file attach in the composer (e.g. `fix @src/foo.py`) |
| `Ctrl+O` / `F6` | Toggle expanded tool output (`/expand`) |
| `Ctrl+Space` | Toggle cockpit / compact layout (`/cockpit`) |
| `Ctrl+P` / `F3` | Plan mode |
| `Ctrl+B` / `F4` | Build mode |
| `Ctrl+T` / `F7` | Toggle thinking trace (expanded by default) |
| `F2` | Flash status on the footer (`Ctrl+S` is not bound; terminals use it for XOFF) |
| `F5` | Refresh live models from the API, then pick |
| `Tab` | Cycle slash completions (`Enter` always submits) |

Drag-select, copy, and right-click paste stay with the terminal (mouse capture off by default). Set `KITE_MOUSE=1` for slash-menu wheel scroll (then use Shift+drag to select in most terminals).

While a turn runs, the bottom toolbar shows a **running line** (`[HH:MM:SS] label running`) and, when bash or background jobs stream output, the latest sanitized line as `› …`. Queued messages show separate **steer** and **follow-up** counts plus `next steer:` / `next follow-up:` preview. Provider retries tick down in the running line. Auto-compaction shows `compacting context`. Metrics row: tok/s, cache %, context meter, and session cost.

`/thinking` and `/fast` appear in the menu only when the current model’s API advertises both effort modes (e.g. OpenRouter, Groq, Nemotron). Use `/reasoning` when only one mode exists.

---

## 3. Prompt slashes (skills, markdown commands, plugins)

These **are** the next user turn. Overlay (later wins): bundled → `~/.kite/commands` → plugins → `.kite/commands`. Skills fill names that nothing else took. Builtins always win.

### Bundled commands (`data/commands/`)

| Command | Use |
|---------|-----|
| `/explain [path or question]` | Explain the repo or a focus |
| `/fix [test or error]` | Diagnose and patch a failure |
| `/pr [notes]` | Draft a PR title and body |

`$ARGUMENTS` (and `$1`…`$9`) in the markdown file is replaced with whatever you typed after the command.

### Bundled skills (`data/skills/`)

Bundled skills are **trusted** (shipped with Kite). npm, git, project, and user-installed skills are **untrusted** — the model sees `trust` and `origin` in listings and invocations. See [SECURITY.md](SECURITY.md).

| Command | Same as |
|---------|---------|
| `/commit` | `/skill commit` or `/skill:commit` |
| `/debug` | `/skill debug` |
| `/review` | `/skill review` |
| `/test` | `/skill test` |
| `/orchestrate` | `/skill orchestrate` (todo + task + subagent fan-out) |
| `/research` | `/skill research` (Context7 / websearch / webfetch) |
| `/pr` | `/skill pr` (branch check, gh pr create) |

If a project command is also named `commit`, `/commit` runs the markdown file; `/skill:commit` still loads the skill.

### Add your own

```
# Install from the web into ~/.kite/skills (shows as /name ~)
/skills add @scope/pkg
/skills add npx some-skill
/skills add owner/repo
kite skills --add owner/repo

# Link a local skill folder into ~/.kite/skills (symlink; copy if the OS refuses)
/skills add ./my-skill
/skills add ~/code/hatch-pet

# Project prompt  ->  /ship
.kite/commands/ship.md

# User prompt     ->  /ship  (unless the project file exists)
~/.kite/commands/ship.md

# Plugin
.kite/plugins/my-kit/plugin.toml
.kite/plugins/my-kit/commands/*.md
.kite/plugins/my-kit/skills/*/SKILL.md
```

Command file shape:

```markdown
---
name: ship
description: Cut a release
argument-hint: [tag]
---

Follow this playbook.

$ARGUMENTS
```

Scaffold from the REPL: `/commands new ship` · `/plugins init my-kit`.

List: `/commands` `/skills` `/plugins` or `kite commands` / `kite skills` / `kite plugins`.

---

## 4. Agent tools (model-called, not typed by you)

**Plan mode:** `read` `grep` `glob` `ls` `task` `webfetch` `websearch` `webcrawl` `skill` `memory` `todo_read` `todo_write` (inspection `bash` only at runtime).

**Build mode adds:** `write` `edit` `bash` **`submit`**.

| Tool | Purpose |
|------|---------|
| `submit` | Structured completion — `message` with Done / Changed / Verification sections (preferred over bash echo marker) |
| `bash` | Inspect (`rg`, `head`, `pytest`, …) or legacy `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` |
| `memory` | Durable notes (`list` / `remember` / `forget`), not the chat log |
| `websearch` | Auto: Tavily → Exa → Firecrawl when keys set; else DuckDuckGo. Returns titles/URLs/snippets |
| `webfetch` | Firecrawl scrape when `FIRECRAWL_API_KEY` set; else stdlib HTML extract |
| `webcrawl` | Firecrawl crawl when keyed; else same-origin stdlib crawl |

Composer: `@path` completes attach paths (word-boundary `@`). Agent flow: `websearch` → pick URL → `webfetch`.
Keys: `kite web-keys set tavily|exa|firecrawl` or `kite keys --set …` → `~/.kite/.env` (owner-only).

`KITE.md` / `AGENTS.md` are repo instructions; `/remember` is durable facts; `/user` + `/profile` + `/working` are global identity context. See [CONTEXT.md](CONTEXT.md) (Memory & persistence).

**Verification:** after edits, run the applicable check for the touched package. Monorepos may need per-service checks. Override defaults in `.kite/verification.toml` (see `src/kite/data/verification.example.toml`).

---

## 5. Where files live

```
~/.kite/
  config.toml          # default provider/model
  commands/*.md        # your slash prompts
  skills/*/SKILL.md
  plugins/<id>/
  memory/MEMORY.md     # semantic facts (opt-in in prompt)
  memory/WORKING.md    # working rhythm — soft habits, in prompt when present
  memory/episodes.sqlite
  sessions/*.jsonl
  approvals.json

<repo>/.kite/
  SYSTEM.md                 # optional: replace bundled system prompt (pi/Prime style)
  APPEND_SYSTEM.md          # optional: append after the base prompt
  verification.toml         # optional: per-repo verification overrides (monorepo)
  commands/*.md
  skills/
  plugins/
  memory/MEMORY.md          # project semantic notes
  memory/episodes.sqlite
```

**System prompt overrides** (same idea as pi / Prime Agent):

| File | Effect |
|------|--------|
| `.kite/SYSTEM.md` or `~/.kite/SYSTEM.md` | Replace the bundled base prompt (project wins) |
| `.kite/APPEND_SYSTEM.md` or `~/.kite/APPEND_SYSTEM.md` | Append after the base (project wins); skills/context still follow |

Harness override (`--system-prompt` / config) still beats discovered `SYSTEM.md`.

Human commits are the source of truth for the project. Checkpoint `kite:` commits exist so `/undo` can revert agent edits without touching your own history.

---

## Security & privacy

Kite is **local-first**: credentials stay on disk under `~/.kite/` (or provider runtimes for BYOS). See [SECURITY.md](SECURITY.md) for the full policy.

| Topic | Control |
|-------|---------|
| **Session persistence** | `session_persistence` in `~/.kite/config.toml`: `redacted` (default), `full`, or `disabled`. REPL: `/privacy sessions …`. CLI: `kite config --session-persistence …` or `kite privacy` |
| **Secret redaction** | Recursive sanitizer for audit logs, events, session JSONL, and tool output (nested dicts/lists, Bearer tokens, sensitive keys) |
| **Child processes** | Credential-like env vars stripped (incl. Tavily/Exa/Firecrawl/Context7); `extra` overrides cannot re-inject secrets. Process trees killed on timeout/cancel |
| **Web tool keys** | Optional `TAVILY_API_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` via `kite web-keys set …` or `kite keys --set …` → `~/.kite/.env` (same secure write as BYOK) |
| **Skills** | Bundled = trusted; npm/git/project/user = untrusted (`.kite-provenance.json` on install) |
| **HTTP tools** | SSRF + peer IP check; redirects capped; crawl budgets |
| **OS/hardware** | `/proc` `/sys` `/dev` protected; bash blocks sudo/docker/kubectl/mount; filtered child env on all subprocess tools |
| **Restricted mode** | Paths clamped to workspace; **all** network tools blocked (bash curl, web*, Context7) |

---

## 6. Install & development

### Install (global — any workstation)

Install once per user. `kite` is then available from any directory.

**macOS / Ubuntu / Linux / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash -s -- --setup
```

**Windows:**

```powershell
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
# If blocked: powershell -NoProfile -ExecutionPolicy Bypass -Command "irm …/install.ps1 | iex"
```

Needs `curl` + `git`. Update / uninstall: `uv tool upgrade kite` · `uv tool uninstall kite`

Contributor (optional): `./scripts/install.sh --dev` still puts `kite` on PATH (editable). Update / uninstall: `uv tool upgrade kite` · `uv tool uninstall kite`.

Manual: `uv tool install "git+https://github.com/KhanUzeb/kite.git"` then `uv tool update-shell`. Then `kite setup`.

### CI

GitHub Actions (`.github/workflows/tests.yml`) runs `pytest` on every push and pull request to `main` (Python 3.11 + 3.12). See [CONTRIBUTING.md](CONTRIBUTING.md#ci-github-actions).

### Use on any project (not the kite checkout)

Install once (one-liner). After that, `kite` is on PATH — no need to activate a venv or sit inside the kite repo.

| What you do | Effect |
|-------------|--------|
| `cd /path/to/my-app` then `kite` | Workspace = `my-app` |
| `kite run --cwd /path/to/my-app "…"` | Same workspace, no `cd` |
| `kite context --cwd .` | Preview discovery for cwd |

`--cwd` is on `run`, `chat`, `resume`, `context`, `skills`, `commands`, `plugins`, `memory`, `apply`, `import`, and `cloud apply`.

Global: `~/.kite/` (sessions, config, user skills). Also loads skills from `~/.agents/skills` on any machine. Per-repo: `<repo>/.kite/commands`, `skills`, `plugins`, `memory`, and `<repo>/.agents/skills`.

### Tests & lint (CI parity)

```bash
python scripts/sync_version.py --check
ruff check src tests
pytest -q
kite bench --check
```

See `tests/README.md` for the compact pytest map (~150 tests: security, approval, agent, CLI/UI, providers).
