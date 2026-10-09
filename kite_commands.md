# Kite commands

Kite is a coding agent. **What lands in git is still yours.** These commands steer the process, not a second commit stream.

**New to Kite?** Start with the visual [guide.md](guide.md) (workflows, example Q&A). This file is the complete reference.

**Help:** `kite --help` lists every shipped subcommand; `kite <subcommand> --help` does not load credentials. `/help` stays brief in the REPL; `/help all` and `kite help all` print the full map. Missing-key errors point to `kite keys --set <provider>`.

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

`kite --help` lists the full command surface. `chat` and `exec` are first-class (exec is the CI one-shot).

**Interactive session:** `kite` is a lean Pi-style REPL (Rich + prompt_toolkit): a branded startup card (logo, version, provider/model, workspace, project instruction files), the composer, and the footer.

Pi-shaped shortcuts:

```
kite                         # lean REPL
kite "fix the tests"         # opening prompt (TTY → chat, else run)
kite -c                      # continue latest session
kite -r                      # browse sessions
!pytest -q                   # in REPL: run shell, send output to the model
!!git status                 # run shell only
/hotkeys                     # keyboard map
```

```
kite --version
kite chat [--mode plan|build] [--approval auto|approve|trust|readonly] [--session id]
kite run "task"              # one-shot
kite run --print "task"      # one-shot, final answer on stdout only (Pi -p style)
kite --print "task"          # same one-shot stdout-only form, no subcommand needed
kite resume <session-id>                 # open that transcript in chat
kite resume <session-id> [follow-up]     # one-shot continue
kite resume --last [--retry]             # newest session for cwd; --retry sends recovery follow-up
kite resume abc12345                     # id prefix works when unique
kite sessions                            # table: date, time, title, model, status, id
kite sessions humanize                   # filter by title, cwd, date, or id prefix
kite sessions -q docs                    # same filter flag
kite sessions --no-pick                  # print table only (no picker)
kite sessions --show <id> [--tail N]     # meta + transcript tail + resume hint (`--tail 0` = full)
```

Sessions with a missing, corrupt, or oversized header remain listable, resumable, and eligible for pruning/deletion: fallback metadata is derived from the filename and labeled **Recovered session**. `kite sessions --limit 0` (or a negative limit) returns no rows; `--tail 0` still means the full transcript.

Shared flags on `run` / `chat` / `resume`:

| Flag | Meaning |
|------|---------|
| `-p` / `--provider` | Catalog name (`openai`, `anthropic`, `zen`, `go`, `nvidia`, …) |
| `-m` / `--model` | Model id within that provider |
| `--cwd` | Workspace |
| `--config` | Runtime TOML name or path |
| `--mode plan\|build` | Read-only checklist vs apply edits |
| `--approval yolo\|auto\|supervised\|approve\|trust\|readonly` | **Coding blanket** (default `auto`): in-workspace install/test/edit/commit auto-runs, including `powershell -Command` / `cmd /c` wrapping those tools. **SERIOUS** still prompts for network fetch, destructive deletes, `chmod`. **Enter** / `a` allows that exact command for the rest of the session; `s` allows the command family; `p` persists to `~/.kite/approvals.json`. CRITICAL (outside workspace, sudo) always prompts / denies headless. |
| `--steps` `--cost` `--time` | Limits (honored by `run`, `chat`, and one-shot `resume`) |
| `--long` | Long-task mode: higher step/cost limits, phased checkpoints, long-task prompt |
| `--no-context` `--no-compact` `--no-guardrails` | Opt out of injection, compaction, sandbox |
| `--attach PATH` | Attach a file or image (repeatable). Images route to a live vision model. Missing paths exit 2 before the REPL starts. |
| `--role` | `auto` / `architect` / `implementer` / `debugger` |
| `-v` | Verbose tool bodies |

Provider requests use the configured `[agent].model_timeout_seconds` from runtime TOML (default `180`). Stream startup and recovery requests use that timeout rather than an additional hard-coded 30-second limit.

One-shot / headless flags (`kite run`, `kite resume <id> "continue"` — not `kite chat`):

| Flag | Meaning |
|------|---------|
| `-q` / `--quiet` | Suppress live events; still show the final run summary |
| `--headless` | Line-oriented stderr log (`[tool]`, `[crew]`, `[out]`), no TTY prompts — CI / cloud agents |
| `--no-stream` | With `--headless`, hide live bash/tool output lines |
| `--json` | Final run status and submission as JSON on stdout (not a stream of events) |
| `-o PATH` / `--output PATH` | Write the trajectory |
| `--label` | Session label |

Persistent compaction is `kite config --auto-compact true|false` (not a run/chat flag).

LLM compaction prefers OpenRouter free-tier (`compaction_provider` / `compaction_model` in `~/.kite/config.toml`); when OpenRouter is unavailable (no key, empty free list, all retries fail) it falls back to the session model — billed/metered, unlike free-tier. Opt out with `compaction_fallback_session = false` (or `compaction_use_llm = false` for deterministic summaries only).

`--headless` also activates when stdout is not a TTY or with `-q`. Approval policy is never weakened: `readonly` blocks mutations, `approve` denies mutations when no prompt is available, and `auto`/`yolo` permit routine in-workspace work (installs, tests, commits) while **SERIOUS** actions (network fetch, destructive delete, shell wrappers) prompt in `auto` and `yolo` skips those prompts; critical gates (outside workspace, sudo, remote shell) fail closed.

One-shot `run` and `resume` share run-result exit codes: **0** submitted successfully, **1** other failure, **2** cancelled/interrupted, **3** approval denied, **4** verification failed. Leftover background jobs prevent a false success even when the model submitted.

**Tool philosophy:** inspect with **bash** (`rg`, `head`, `sed -n`, `wc -l`) for token-efficient peeks; use `read` only for bounded slices; `set_cwd` when the user names another directory.

**Tool batching:** on by default when the provider supports multiple tool calls per turn. Read-only tools batch freely; `write`/`edit` run in parallel only on **disjoint paths**; reads may run alongside writes when paths do not overlap. `bash` stays sequential. Loop guard tolerates more read-only repeats before warning.

Housekeeping (no model):

```
kite sessions                  # TTY: table then pick → resume / show / delete
kite sessions [query]          # filter by title, cwd, date, or id prefix
kite sessions -q text          # same as positional filter
kite sessions [--limit N] [--show id] [--tail N] [--no-pick]
kite sessions --delete <id> [<id> ...]
kite sessions --delete-all     # TTY confirms; else pass -y
kite sessions --prune 20 -y    # keep newest 20, delete the rest
kite setup [-p provider]       # first-run wizard: credentials + model
kite update [--check] [--ref REF] [--force]  # upgrade installed CLI via uv tool (fallback: git reinstall); bare `kite update` updates, it does NOT open chat
                                # Windows: the running install is file-locked, so the update runs in a helper
                                # after this process exits — progress streams in the SAME terminal (under the next
                                # prompt); confirm with `kite --version` in a new terminal
kite uninstall [-y] [--purge]  # remove CLI; keeps ~/.kite data unless --purge (--purge retries read-only files and reports leftovers)
kite login [provider]          # pick provider if omitted → BYOK key or BYOS browser → pick model
                                # BYOS (chatgpt/claude/grok/antigravity): opens your browser to the sign-in URL
                                # as soon as the provider CLI prints it (grok uses `grok login --oauth`
                                # interactively, `--device-auth` when headless); ChatGPT opens the OAuth/device
                                # URL too. `agy` drives its own Google sign-in (launch `agy`:
                                # silent keyring on local machines, browser when needed, manual URL
                                # loop over SSH — the only official method, see
                                # https://antigravity.google/docs/cli/install/). Kite verifies the
                                # session with read-only `agy models` and only then marks linked
                                # (quitting `agy` without signing in does NOT link); only auth URLs
                                # are ever surfaced. Linked sessions are re-verified at most once a
                                # day, so status checks stay instant.
                                # Already linked → reuses the session (no browser) and jumps to model pick.
                                # `kite login grok` also bridges tokens to LiteLLM under ~/.kite/oauth/xai
                                # via the xAI subscription chat proxy. Claude stays CLI-owned
                                # (calls need ANTHROPIC_API_KEY); Antigravity answers through
                                # the signed-in agy CLI (`agy -p --mode plan`, text-only —
                                # GEMINI_API_KEY adds direct calls with tool support).
kite logout [provider]         # unlink BYOS subscription (codex, claude, grok/xai, antigravity)
                                # antigravity also needs `/logout` inside `agy` to purge its keyring
                                # session (Kite only held a linkage marker).
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
kite theme [name] [--list]     # TTY: typed number/name pick (same as /theme)
kite font [name] [--list]      # TTY: typed unicode|ascii pick (same as /font)
kite variants [level] [--list] [-p provider] [-m model]  # thinking variant (same as /variants)
kite config [--set-provider …] [--set-model …] [--select-model] [--set-api-base …]
              [--session-persistence full|redacted|disabled]
kite privacy [--session-persistence full|redacted|disabled]   # security policy summary
kite context [--json] [--refresh]
kite init [dir] [--force] [--chat] [--agents-only|--kite-only]  # scaffold AGENTS.md (+ KITE.md)
kite skills                    # TTY: pick a skill to show (trust/origin column)
kite skills [--show name] [--add pkg|path]
kite commands
kite plugins
kite memory [--remember text] [--forget query] [--project]
kite runtime-config [--config name]
kite bench [--suite quick|full] [--json] [--save PATH] [--compare BASELINE.json] [--check] [--ab] [--stress]
kite tasks init [--force] [path]              # write example ~/.kite/tasks/example.jsonl
kite tasks run <file.jsonl> [--stdin] [--json] [--dry-run] [--continue-on-error]
                           [--steps N] [--cost USD] [--time SEC] [-p] [-m]
kite subagents [--show id] [--init id] [--role architect] [--force]
kite dashboard [--session id] [--json] [--watch SEC] [--limit N]
kite gh issue view|list|create|comment [--repo owner/name]  # view/list/create/comment on issues (any repo via --repo)
kite gh pr view|list|create [--repo owner/name]             # same for PRs
kite gh auth [login|status|logout]  # browser/device login, `--with-token` PAT-from-stdin for headless; also reads GH_TOKEN/GITHUB_TOKEN
```

### Harness timing (`kite bench`)

Repeatable benchmarks for the **harness only** — no live LLM calls. Use before/after refactors on the same machine, Python, and workspace.

```bash
kite bench                         # quick suite: name · category · median ms
kite bench --json                   # machine-readable report
kite bench --check                  # quick CI timing budgets; exit 1 on failure
kite bench --suite full --save before.json
# apply a change, then compare and retain the new report
kite bench --suite full --compare before.json --save after.json
```

The default **quick** suite covers startup, context, and tools with temporary fixtures; it never writes `src/app.py` into your cwd. `--cwd PATH` measures that workspace's context without modifying it. Budget ceilings live in `src/kite/bench/budgets.py`; `pytest tests/test_bench.py` exercises the quick budgets.

The **full** suite has 43 measurements: cold-start subprocesses, 50/80/120-column streaming, 20k answer/reasoning events, 10k-option picker navigation, 50/200-turn stub-agent and prompt-cache growth, repo-map/grep/path completion on a generated 20,000-file tree, and large-session append/list/resume/reverse reads (2,000 metadata-only sessions and 50 MB transcripts). It also covers an explicit Console width without an explicit height under `TERM=dumb`. Session workloads use a temporary `KITE_HOME`; fixture setup/removal is outside individual timings. Cold means **process-cold**, not a flushed OS filesystem cache. Full-suite extras are diagnostic, not absolute CI budgets; the reasoning-volume workload measures accumulation, not final replay.

`--save PATH` writes a report with medians, samples, and median absolute deviation (MAD). `--compare PATH` exits 1 only when a slowdown exceeds **all three**: `--threshold` (default 20%), `--min-delta` (default 2 ms), and three times the sum of before/after MAD. Incompatible benchmark names, platform, Python minor version, or workspace also fail comparison. This is a noise guard, not a statistical significance claim: repeat isolated runs and never compare profiled timings against unprofiled baselines. `--save` works with `--compare`, including failed comparisons.

Optional: `--ab` and `--stress` (outside CI pytest); neither combines with `--suite full`, `--compare`, or `--check`.

### Runtime event tracing

```bash
KITE_TRACE_JSONL=/tmp/kite-trace.jsonl kite run --headless "fix the failing test"
```

`KITE_TRACE_JSONL` opts into an append-only JSONL record of every runtime event, independent of live terminal display. Each line has `t` (monotonic seconds since run start), `ts` (Unix timestamp), `run_id`, `type`, and the event's payload fields at the top level. Reserved timing/identity fields cannot be overwritten by payloads. An open/write failure emits one stderr warning and disables tracing for that run without failing the task. This is distinct from `/trace`, which shows the last traceback.

For permissions, redaction, and field bounds see [SECURITY.md](SECURITY.md#runtime-trace-files); for lifecycle and event fan-out see [architecture.md](architecture.md#event-driven-ui).

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

Dispatch at runtime: `subagent` tool with `profile=<id>` and `prompt=…`. Optional per-worker **`model=`** and **`provider=`** (or `models` / `providers` arrays for parallel crews). When you ask for crews or name profiles in plain language, the agent should dispatch `subagent` directly. User-authored profiles are wrapped as untrusted content.

Crew execution notes: sibling sync `subagent` calls in one turn auto-merge into a single parallel crew (async/background and `wait_for` collects stay separate). Workers start with fresh context but receive the parent's open todos automatically (explicit `context=` wins). Handoffs carry `files_touched` + `cost`/`tokens`/`calls`: worker spend counts against the parent budget (`total_cost`), and worker-touched files join parent checkpoint tracking.

`kite dashboard` is per-user: it reads your local `~/.kite/sessions` (or `$KITE_HOME`). Overview: active/failed runs, exit statuses, provider/model usage, tool breakdown, cost, tokens, cache, subagents, and sessions needing attention. `--session <id>` drills into one run (cwd, mode, verification, tool failures, event timeline). `--watch 5` refreshes every 5 seconds.

---

## 2. REPL control slashes

These never go to the model.

| Command | What it does |
|---------|----------------|
| `/build` `/b` | **Default** — apply edits, run tests, submit; continues any plan checklist |
| `/plan` `/p` | **Opt-in** — read-only explore + checklist; switch to `/build` to apply |
| `/approve yolo\|auto\|supervised\|trust` | Autonomy. Empty: numbered picker. `auto` (default) = coding blanket (install/test/edit/commit); prompts for curl/wget/rm/chmod/PowerShell wrappers; `yolo` = skip non-critical prompts; `trust` = blanket + memory/subagent gates; `supervised` = approve every mutation |
| `/trust [on\|off\|status]` | **Project trust** (Pi-style). Trusted cwd skips nested-agent approval prompts. First run may prompt when `.kite/plugins` or `.kite/extensions` exist |
| `/reload` | Reload skills index, slash commands, and subagent profiles without restart |
| `/restricted on\|off` `/sandbox` | Path sandbox (default **off**). Empty: pick on/off |
| `/privacy` | Security policy summary; `/privacy sessions` picks full/redacted/disabled |
| `/privacy sessions redacted\|full\|disabled` | Set session JSONL persistence (default **redacted**) |
| `/theme [auto\|kite\|dark\|light\|dim\|mono\|monochrome\|catppuccin\|ember\|forest\|hues\|transparent]` | Color palette. Empty: pick |
| `/font [unicode\|ascii]` | Glyph pack. Empty: pick |
| `/thinking` `[off\|minimal\|low\|medium\|high\|…]` | Pi-style thinking level for the current model. Empty: **cycle** to the next level. `off` hidden when the model cannot disable reasoning. Unsupported levels clamp to the nearest supported one with a notice (e.g. `xhigh` on a low/high-only model → `high`) |
| `/variants [level]` | Thinking variant for the current model — **strictly** limited to levels it supports (no clamping; unsupported names are rejected with the offered list). Empty: typed pick. `auto` clears the saved override. Saved as the default for fresh sessions; shown as `provider/model#variant` in the status line |
| `/model [provider/id]` | Show or set model |
| `/model provider/id --save` | Set model and persist to `~/.kite/config.toml` |
| `/select [provider]` | Pick provider if needed, login if unlinked, then pick a live model (saved) |
| `/models [provider [model]]` | Pick a live model and save to `~/.kite/config.toml`. Empty: pick provider first. Two+ provider names: pick among them |
| `/models refresh [provider]` `/refresh` | Clear the model cache, re-fetch from the provider API, then pick (also **F5**) |
| `/provider [name]` | Empty: same connect flow as `/select`. With a name: set provider |
| `/login [provider]` | Always (re)link credentials, then pick a model. BYOS opens a browser to the live sign-in URL (ChatGPT OAuth/device, Grok `--oauth` / device code, Antigravity via `agy`); already-linked sessions skip the browser |
| `/logout [provider]` | Unlink; omit provider to pick |
| `/sessions` `/session list` | Numbered picker: open / show / delete |
| `/session open [id]` `/resume [id]` | Continue that chat (prints last 30 of the transcript — full history still loads for the turn); omit id to pick a card — prompt on top, project · age · size · status beneath; current folder first |
| `/session prune [N]` | Delete all but the newest N sessions (default 20, confirms first) |
| `/keys` | Credential status with type (BYOK/BYOS), masked key fingerprint, OAuth link state |
| `/reasoning` `/effort` | Legacy effort modes (`auto\|off\|fast\|thinking`) — prefer `/thinking` |
| `/fast` | Legacy shortcut → `/thinking low` |
| `/undo` | Revert last **kite:** git checkpoint (agent edits only) |
| `/clear` | Fresh chat session (memory notes stay) |
| `/new` | Start a new session — clears history and pending state, keeps provider/model/config |
| `/usage [session\|provider\|all]` | Token, cache, cost, context, and provider limits (missing provider data never errors) |
| `/compact` | Summarize older turns now; ctx meter updates immediately |
| `/cost` | Legacy alias → `/status` (includes cost) |
| `/stop` | Stop the current turn; session stays open |
| `/steer text` | Inject `text` into the running turn (queues when idle); the turn continues with the correction |
| `/tasks` | Show the running turn and queued follow-ups, plus the full itemized task checklist (the live line shows one compact row) |
| `/last` | Re-print the last tool call’s full output or diff (tool bodies print capped to 5 lines) |
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
| `/session show [id] [--tail N]` | Preview transcript (default 20 messages; `--tail 0` = full) |
| `/session delete [id\|all]` | Drop this (or another) transcript + trajectory |
| `/init` | Scaffold `AGENTS.md` (+ `KITE.md` stub). Flags: `--force`, `--agents-only`, `--kite-only` |
| `/context` | Preview project context (verify line, bootstrap/git hints). `/context refresh` bypasses cache |
| `/expand` | Toggle expanded tool output |
| `/live` | Stream bash output in real time while tools run |
| `/live agents` | Stream subagent crew tool + shell output with worker prefix |
| `/collapse` | Collapse tool output (default) |
| `/trace` | Last traceback |
| `/tools` | Built-in agent tools grouped by family (○ inspect · ✎ edit · $ shell · ↗ net · ◈ crew) |
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
| `/help` `/h` | Essential commands (15). `/help all` adds legacy aliases, shortcuts, and doc pointers (`kite_commands.md`, `CONTEXT.md`, …) |
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
| `Ctrl+G` | Steer: redirect the running turn with the composer text (same as `Enter` while busy); the composer stays pinned |
| `Ctrl+U` | Dequeue: restore all queued messages into the composer for editing |
| `F9` | Fold a long composer paste to first lines + `+N lines` (any key expands; `Enter` submits the full text) |
| `Enter` | Send the line. With an open slash menu, accept the highlighted completion first. **While a turn runs:** steers (redirects) by default — set `KITE_BUSY_ENTER=queue` for legacy queue-on-Enter |
| `Alt+Enter` | Newline when idle. **While a turn runs:** queues a follow-up (steer when `KITE_BUSY_ENTER=queue`) |
| `Shift+Tab` / `Ctrl+P` / `F3` | Plan mode |
| `@path` | Inline file attach in the composer (e.g. `fix @src/foo.py`) |
| `Ctrl+O` / `F6` | Toggle expanded tool output (`/expand`) |
| `Ctrl+B` / `F4` | Build mode |
| `Ctrl+T` / `F7` | Toggle thinking trace (collapsed by default — one-line summary) |
| `F2` | Flash status on the footer (`Ctrl+S` is not bound; terminals use it for XOFF) |
| `F5` | Refresh live models from the API, then pick |
| `Tab` | Cycle slash completion selection without submitting |

Slash completion menus highlight the first match automatically. `↑` / `↓` wrap through matches, Page Up/Down move by a page, and selection leaves the typed input unchanged until `Enter` accepts it.

`@path` completion expands `~`, gives directories a trailing slash, and shows no candidates for a missing directory (rather than listing cwd). Multi-select pickers retain checked entries when a filter hides them.

Model/provider/session pickers (`kite models --select`, `kite select`, `kite -r`, `/select`, setup, web-keys) use a **console list**. On a TTY: **↑↓**, Page Up/Down, **click or drag** a row then release to select, type to filter, type a **number** then Enter, `r` refresh, Esc/`q` cancel. CI/`KITE_TYPED_PICK=1` uses the typed prompt (`+/−` pages). Composer mouse capture is **off** by default so the welcome banner stays readable on Windows; `KITE_MOUSE=1` enables slash-menu wheel (Shift+drag to copy).

The busy hint reads **Enter steers** by default, or **Enter queues** only with `KITE_BUSY_ENTER=queue`.

While a turn runs, the bottom toolbar shows a **running line** (`[HH:MM:SS] label running`) and, when bash, background jobs, or the answer text stream output, the latest sanitized line as `› …`. The footer stays fed for the whole turn: the answer tail mirrors into the running line while it generates, and a finished tool hands the spinner straight to the next model call, so there is no silent window between events. Model streaming shows `streaming` with **ttft** (time-to-first-token) on early tokens, then **tok/s** from provider usage when available. Reasoning and answer text use separate channels; tool-call JSON streams as throttled `preparing` previews. Queued messages show separate **steer** and **follow-up** counts plus `next steer:` / `next follow-up:` preview. Provider retries tick down in the running line. Auto-compaction shows `compacting context`. A failed turn leaves a persistent error segment in the footer until the next turn starts. Metrics row: tok/s, cache %, context meter, and session cost.

When stderr is not a TTY (pipe, relay, CI log) there is no `\r` animation to watch, so the loader emits newline-delimited heartbeat lines instead — starting at 2s and backing off to 15s. `tools.progress_interval_seconds` (default `2.0`) bounds the silence between `tool_progress` events; `KITE_TYPED_PICK=1` forces typed pickers and `KITE_NO_MOUSE_PICK=1` keeps the picker off the mouse.

Diffs render with a dim **old/new line-number gutter** derived from the hunk headers, a paired `-`/`+` word-level highlight, and a `+adds,-dels` histogram in the header. `/collapse` and `/expand` switch the body between the first `DIFF_PREVIEW_LINES` rows and the full patch.

Streamed paragraphs wrap to the terminal's cell width, including narrow 50/60/80/120-column layouts, wide Unicode characters, and expanded tabs; chunk boundaries do not split words. Deferred answers retain their opening chunks beyond 2,000 deltas, and expanded reasoning is not replayed twice.

`/thinking` appears in the slash menu when the current model advertises reasoning/thinking support. Levels shown match what the API exposes (e.g. `off low medium high` on OpenRouter/Groq/Nemotron). Empty `/thinking` cycles like Pi; set explicitly with `/thinking high` or `/thinking off`. Unsupported levels clamp to the nearest supported one and report it.

---

## 3. Prompt slashes (skills, markdown commands, plugins)

These **are** the next user turn. Overlay (later wins): bundled → `~/.kite/commands` → plugins → `.kite/commands`. Skills fill names that nothing else took. Builtins always win.

### Bundled commands (`data/commands/`)

| Command | Use |
|---------|-----|
| `/explain [path or question]` | Explain the repo or a focus |
| `/fix [test or error]` | Diagnose and patch a failure |
| `/pr [notes]` | Draft a PR title and body |
| `/unslop [file, diff, or focus]` | Remove AI-generated cruft (verbose prose, redundant comments, unused helpers) without changing behavior |

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

**Plan mode:** `read` `grep` `glob` `ls` `task` `webfetch` `websearch` `webcrawl` `skill` `memory` `todo_read` `todo_write` `question` (inspection `bash` only at runtime).

**Build mode adds:** `write` `edit` `bash` **`submit`** (plus `question`).

| Tool | Purpose |
|------|---------|
| `submit` | Structured completion — `message` with Done / Changed / Verification sections (preferred over bash echo marker) |
| `question` | Clarifying questions for genuine ambiguity (opencode-style: header/question/options, number or free text, skippable). Interactive REPL answers live; headless runs get an empty set and proceed on assumptions |
| `write` / `edit` | Edits preserve the file's on-disk line endings (no LF↔CRLF churn); new files default to CRLF on Windows / LF elsewhere unless `.gitattributes`/`editorconfig` say otherwise |
| `bash` | Inspect (`rg`, `head`, `pytest`, …) or legacy `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`. Runs with the project `.venv` first on PATH when one exists (system toolchains otherwise). Dynamic `gh` lives here too (no hardcoded tools needed): read-only `gh issue/pr view\|list` runs free in build AND plan mode; publishing commands (`create`/`comment`/`merge`/`close`) prompt for approval in auto mode |
| `grep` | Search with a global `max_hits` limit and bounded context; colons in content remain intact, and a direct-file search shows that file's name in the heading |
| `memory` | Durable notes (`list` / `remember` / `forget`), not the chat log |
| `websearch` | Auto: Tavily → Exa → TinyFish → Firecrawl when keys set; else DuckDuckGo. Short paid results are topped up from DuckDuckGo; Tavily answers surfaced. Returns titles/URLs/snippets |
| `webfetch` | Firecrawl scrape when `FIRECRAWL_API_KEY` set; else stdlib HTML extract (nav/footer chrome stripped) |
| `webcrawl` | Firecrawl crawl when keyed; else same-origin stdlib crawl |
| `gh_auth` | Read-only GitHub auth probe — call when `gh_*` tools report auth errors (hint points at `kite gh auth login` / `GH_TOKEN`) |

Agent flow: `websearch` → pick URL → `webfetch`.
Keys: `kite web-keys set tavily|exa|tinyfish|firecrawl` or `kite keys --set …` → `~/.kite/.env` (owner-only).

Background bash jobs enforce their timeout even when the child produces no output, and retained logs preserve newlines. For output caps and omitted-line notices, see [SECURITY.md](SECURITY.md#bounded-output-capture).

`KITE.md` / `AGENTS.md` are repo instructions; `/remember` is durable facts; `/user` + `/profile` + `/working` are global identity context. See [CONTEXT.md](CONTEXT.md) (Memory & persistence).

**Verification:** after edits, run the applicable check for the touched package. Monorepos may need per-service checks; nested Go modules suggest commands such as `cd services/api && go test ./...`. Override defaults in `.kite/verification.toml` (see `src/kite/data/verification.example.toml`). Narration and unsupported-verification-claim nudges consume bounded retry budgets. An edited session cannot bypass the submit gate with a casual-chat answer; exhausted-gate messages report the actual blocker.

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
  trust.json                # trusted project roots (Pi-style; /trust on writes here)
  release_check.json        # cached GitHub latest-release check (24h TTL)

<repo>/.kite/
  project.toml              # optional: [project] trust = true skips nested-agent approval
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

**Project trust** (optional, Pi/Codex-style):

| Mechanism | Effect |
|-----------|--------|
| `/trust on` | Record cwd in `~/.kite/trust.json` |
| `.kite/project.toml` → `[project] trust = true` | Repo declares itself trusted (checked in git) |
| Trusted project | Nested `subagent` spawns skip the approval prompt in `auto` / `trust` / `yolo` |

Set `KITE_OFFLINE=1` to skip the background GitHub release check on REPL startup.

Human commits are the source of truth for the project. Checkpoint `kite:` commits exist so `/undo` can revert agent edits without touching your own history. Plan mode never attaches git checkpoints.

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

Needs `curl` + `git`. Update / uninstall: `kite update` · `kite uninstall` (`uv tool upgrade kite` / `uv tool uninstall kite` still work).

Contributor installs (`scripts/install.sh --dev --local`, Windows `install.ps1 -Dev -Local`): see [CONTRIBUTING.md](CONTRIBUTING.md#how-to-set-up).

Manual: `uv tool install "git+https://github.com/KhanUzeb/kite.git"` then `uv tool update-shell`. Then `kite setup`.

### CI

GitHub Actions (`.github/workflows/tests.yml`) runs `pytest` on every push and pull request to `main` (Python 3.11 + 3.12). See [CONTRIBUTING.md](CONTRIBUTING.md#ci-github-actions).

### SoL-Pi (token-efficient harness)

Optional mechanisms from [SoL-Pi](https://arxiv.org/abs/2609.20519) (NVlabs reference: [SoL-Pi](https://github.com/NVlabs/SoL-Pi)). All features are **off** unless enabled in JSON:

| File | Precedence |
|------|------------|
| `<project>/.kite/sol-pi.json` | Project (when present) |
| `~/.kite/sol-pi.json` | User default |

Copy the template from `src/kite/data/sol-pi.example.json`. Keys mirror the paper: `actionFusion`, `observationPack`, `evidencePreservingReducer` (+ optional reducer provider/model), `onlineContextCompact`, and `cacheWriteReadRatio` (default `12.5`). Conservative start: enable only `actionFusion` and `observationPack` (no extra model calls). Archives live under `<project>/.kite/sol-pi/<session-id>/`.

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

See [tests/README.md](tests/README.md) for the pytest map and [AGENTS.md](AGENTS.md#tests--ci) for the dev loop (`ci_check.sh --fast`, `e2e_smoke.py`, `worktree.sh`, `profile_cli.py`).
