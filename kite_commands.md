# Kite commands

Kite is a coding agent. **What lands in git is still yours.** These commands steer the process, not a second commit stream.

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
| `--steps` `--cost` `--time` | Limits |
| `--long` | Long-task mode: higher step/cost limits, phased checkpoints, long-task prompt |
| `-v` / `-q` | Verbose tool bodies / quiet |
| `--no-context` `--no-compact` `--no-guardrails` | Opt out of injection, compaction, sandbox |
| `--auto-compact` | Persist auto-compaction on/off in `~/.kite/config.toml` (`kite config --auto-compact true\|false`) |
| `--attach PATH` | Attach a file or image (repeatable). Images route to a live vision model. |

**Tool philosophy:** inspect with **bash** (`rg`, `head`, `sed -n`, `wc -l`) for token-efficient peeks; use `read` only for bounded slices; `set_cwd` when the user names another directory. inspect with **bash** (`rg`, `head`, `sed -n`, `wc -l`) for token-efficient peeks; use `read` only for bounded slices; `set_cwd` when the user names another directory.

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
kite keys [--set [provider]]   # paste BYOK API keys (hidden); omit provider to pick
kite keys --logout [provider]  # unlink BYOK keys or BYOS (omit provider to pick)
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
kite bench --ab                 # A/B task vs subagent dispatch (time + peak heap)
kite bench --stress             # brute-force orchestrator stress (time + space)
```

See [docs/bench-orchestrate-ab.md](docs/bench-orchestrate-ab.md) for metrics tables and interpretation.

| Category | Benchmarks |
|----------|------------|
| **startup** | `cli_import`, `config_load`, `user_config_load`, `catalog_load`, `skills_load`, `repl_chat_init`, `model_resolve`, `slash_index`, `runtime_prepare` |
| **context** | `repo_map`, `prompt_cache_prepare`, `context_gather`, `prompt_assembly` |
| **tools** | `tool_registry`, `read_tool`, `grep_tool`, `bash_echo`, `subprocess_spawn` |
| **orchestrate** | `task_dispatch`, `orchestrator_sync`, `dispatch_mode` |

Budget ceilings live in `src/kite/bench/budgets.py`. `pytest tests/test_bench.py` runs the same suite in CI.

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
| `/theme [auto\|kite\|dark\|light\|dim\|mono]` | Color palette. Empty: pick |
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
| `/jobs` | List background bash jobs and live subagents (pick to kill) |
| `/agents` | Subagent crew board — labels, status, prompts; `/kill` to stop |
| `/kill [id\|all]` | Kill one background job/subagent, or all. Empty: pick |
| `/session` | Current session id |
| `/session show [id]` | Print a transcript (current if omitted) |
| `/session delete [id\|all]` | Drop this (or another) transcript + trajectory |
| `/init` | Write `KITE.md` if missing |
| `/expand` | Toggle expanded tool output |
| `/live` | Stream bash/job output in real time while tools run |
| `/collapse` | Collapse tool output (default) |
| `/trace` | Last traceback |
| `/skills [name]` | List skills (trust/origin column), or print one. Empty: pick to show. User-home skills show `~` (`~/.kite/skills`, `~/.agents/skills`) |
| `/skills add pkg\|path` | Install npm/npx/GitHub into `~/.kite/skills` (**untrusted** — provenance in `.kite-provenance.json`), or **link** a local skill folder |
| `/commands` | List markdown slash prompts |
| `/commands new name` | Write `.kite/commands/name.md` |
| `/plugins` | List plugins |
| `/plugins init name` | Scaffold `.kite/plugins/name` |
| `/memory [semantic\|episodic]` | Semantic markdown + episodic sqlite |
| `/semantic` | Show `MEMORY.md` notes |
| `/episodic` | Show sqlite episode log |
| `/remember [user\|project] text` | Append a note |
| `/forget id\|substring` | Drop matching notes |
| `/attach path` | Queue a file or image for the next turn (any path on disk) |
| `/clip` `/paste` `/clipboard` | Attach clipboard text or image (**F8** or **Esc v**) |
| `/detach [name\|all]` | Drop queued attachments |
| `/attachments` | List queued files |
| `/help` `/h` | Command map + keyboard shortcuts |
| `/quit` `/q` `/exit` | Leave the REPL |

Ctrl+C stops the **current turn**, not the process.

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
| `websearch` | DuckDuckGo search (no API key); unwraps redirect links; deduped results |
| `webfetch` | Fetch one URL → extracted readable text + title (HTML stripped; JSON pretty-print) |
| `webcrawl` | Same-origin multi-page crawl with depth/page limits |

Composer: `@path` completes attach paths (word-boundary `@`). Agent flow: `websearch` → pick URL → `webfetch`.

`KITE.md` / `AGENTS.md` are repo instructions; `/remember` is durable notes.

**Verification:** after edits, run the applicable check for the touched package. Monorepos may need per-service checks. Override defaults in `.kite/verification.toml` (see `src/kite/data/verification.example.toml`).

---

## 5. Where files live

```
~/.kite/
  config.toml          # default provider/model
  commands/*.md        # your slash prompts
  skills/*/SKILL.md
  plugins/<id>/
  memory/MEMORY.md     # semantic facts
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
  memory/notes.jsonl
  MEMORY.md
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
| **Child processes** | Credential-like env vars stripped; `extra` overrides cannot re-inject `OPENAI_API_KEY`, `GITHUB_TOKEN`, etc. Process trees killed on timeout/cancel |
| **Skills** | Bundled = trusted; npm/git/project/user = untrusted (`.kite-provenance.json` on install) |
| **HTTP tools** | SSRF checks: resolve host → validate all IPs → connect; redirects re-validated |

---

## 6. Install & development

### Install (any workstation)

```bash
git clone https://github.com/KhanUzeb/kite.git && cd kite
./scripts/install.sh                    # macOS/Linux
# .\scripts\install.ps1                 # Windows PowerShell
```

Package maintenance (not `kite` CLI subcommands):

```bash
./scripts/pkg.sh update       # git pull + editable reinstall
./scripts/pkg.sh reinstall
./scripts/pkg.sh uninstall    # optional --remove-venv
# Windows: .\scripts\pkg.ps1 update|reinstall|uninstall
```

One-liner (default install dir `~/kite` or `%USERPROFILE%\kite`):

```bash
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
```

Custom dir: `KITE_INSTALL_DIR=~/tools/kite ./scripts/install.sh` or `.\scripts\install.ps1 -Dir C:\tools\kite`.

Manual: `uv venv --python 3.12` → activate → `uv pip install -e ".[dev]"`. Then `kite setup` (or `kite providers` + `kite models --select`).

### CI

GitHub Actions (`.github/workflows/tests.yml`) runs `pytest` on every push and pull request to `main` (Python 3.11 + 3.12). See [CONTRIBUTING.md](CONTRIBUTING.md#ci-github-actions).

### Use on any project (not the kite checkout)

Install once. Activate the venv (install script prints the path; or add `.venv/bin` / `.venv\Scripts` to `PATH`).

| What you do | Effect |
|-------------|--------|
| `cd /path/to/my-app` then `kite` | Workspace = `my-app` |
| `kite run --cwd /path/to/my-app "…"` | Same workspace, no `cd` |
| `kite context --cwd .` | Preview discovery for cwd |

`--cwd` is on `run`, `chat`, `resume`, `context`, `skills`, `commands`, `plugins`, `memory`, `apply`, `import`, and `cloud apply`.

Global: `~/.kite/` (sessions, config, user skills). Also loads skills from `~/.agents/skills` on any machine. Per-repo: `<repo>/.kite/commands`, `skills`, `plugins`, `memory`, and `<repo>/.agents/skills`.

### Tests

```bash
pytest              # after install.sh or uv pip install -e ".[dev]"
pytest -v
```

See `tests/` for guardrails, approval/trust, loop guard, sessions, verification, orchestrator, caches, and UI helpers.
