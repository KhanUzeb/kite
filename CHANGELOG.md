# Changelog

All notable changes to Kite are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Paid web backends** — optional `TAVILY_API_KEY` / `EXA_API_KEY` / `FIRECRAWL_API_KEY` in `~/.kite/.env` via `kite web-keys set tavily|exa|firecrawl` (or `kite keys --set …`). `websearch` auto-tries Tavily → Exa → Firecrawl → DuckDuckGo; Firecrawl also upgrades `webfetch` / `webcrawl`.

### Fixed
- **ChatGPT BYOS hang** — LiteLLM expects flat `auth.json`; Codex stores nested `tokens`. Kite now materializes a LiteLLM-compatible copy under `~/.kite/oauth/chatgpt/` from the official Codex store so the harness no longer blocks on device-code login.

## [0.9.6] - 2026-09-09

### Added
- **Themes** — palettes (`kite`, `dark`, `light`, `dim`, `mono`, `catppuccin`, `ember`, `forest`, `hues`, `transparent`) wired through TUI chrome; `/theme` and `/font`.
- **Subagent orchestration** — auto sync/async dispatch, `wait_for`, crew TUI, `/agents` board, `/live agents`.
- **Personas** — bundled scout/coder/reviewer/context/shell profiles; `kite subagents` CLI; `~/.kite/subagents/<id>.md` overrides.
- **Global user context** — `USER.md` / `PROFILE.md` (`/user`, `/profile`) plus fluid working rhythm (`WORKING.md`, `/working`).
- **Goal + recovery** — `/goal` persistent objective; resume/retry after provider errors (`kite resume --retry`).
- **Headless tasks** — `kite tasks` JSONL batches and `kite run --headless`.
- **Web tools** — webfetch readable extraction, websearch ranking/dedupe, DuckDuckGo unwrap, crawl budgets.
- **`docs/RELEASE-0.9.6.md`** — release notes for this version.
- **`scripts/download-macos.sh`** and **`scripts/lint.sh`** — macOS bootstrap and contributor lint.

### Changed
- **BYOS authentication** — provider-delegated auth for ChatGPT/Codex (`openai-codex` SDK), Claude Code (`claude auth` CLI), and Grok (`grok` CLI). Removed LiteLLM private OAuth internals.
- **`kite logout`** — unlink BYOS subscriptions (`kite logout codex|claude|grok|xai`). Claude subscription stays separate from Anthropic BYOK; tokens are never copied into `~/.kite/.env`.
- **Slash startup** — first `/` completion prewarms so the REPL menu opens faster.
- **CI** — pytest runs on all pull requests, not only those targeting `main`.

### Security
- Auth errors sanitize token-shaped strings; OAuth secrets are not logged or written to project `.env` files.
- **Recursive secret redaction** — nested audit/event/session/tool payloads sanitized before persistence or display.
- **Session persistence policy** — `full` | `redacted` (default) | `disabled`; owner-only session files when enabled.
- **Process-tree teardown** — timeout/cancel kills child process groups (Unix `killpg`, Windows `taskkill /T`).
- **Environment isolation** — sensitive env keys stripped from child processes; `extra` overrides cannot re-inject credentials.
- **Skill trust model** — bundled trusted; npm/git/project/user untrusted with provenance metadata.
- **SSRF hardening** — resolve → validate all IPs → connect-time peer check; redirect and DNS TOCTOU re-checks.
- **Harness OS protection** — `/proc` `/sys` `/dev` blocked for read/write/bash; restricted mode blocks all network tools (bash, webfetch/websearch/webcrawl, Context7).
- REPL `/privacy` and CLI `kite privacy` / `kite config --session-persistence`.
- System prompt documents harness limits, attachment handling, and user interrupt behavior.
- REPL **F8** / **Esc v** clipboard attach, **Ctrl+L** clear screen; shortcuts in `/help`.

### Fixed
- Windows permission / process-group tests skip Unix-only assertions; bash cancel tests use `sleep`.
- Ruff unused-import failures in BYOS tests; duplicate dict keys in `build_design_pdf.py`.

## [0.9.5] - 2026-09-07

### Added
- **Pi-style runtime steering** — mid-turn corrections inject into the active run and continue the same turn; follow-ups queue at turn boundaries (`RunMessageQueue`, `harness.inject_user_message()`).
- **REPL message inbox** — Enter queues a follow-up while busy; Ctrl+G steers; Ctrl+U dequeue-to-composer; `/steer` and `/tasks`; steer vs follow-up labels on the toolbar.
- **Compaction lifecycle events** — `compaction_start` / `compaction_end` on the agent event bus (durable in session JSONL).
- **Harness timing budgets** — `kite bench --check` and `tests/test_bench.py` enforce median-ms ceilings; budgets in `src/kite/bench/budgets.py`.
- Expanded `kite bench` suite (18 cases): `user_config_load`, `catalog_load`, `slash_index`, `repo_map`, `runtime_prepare`, plus existing startup/context/tool benchmarks.
- **Session browser** — `kite sessions` table (date, time, title, model, status); `kite sessions -q` filter; `kite resume <id>` with prefix match and suggestions.
- **`~/.agents/skills`** — global Agent Skills library loaded on any machine (sandbox read allowed).
- **`docs/RELEASE-0.9.5.md`** — release notes for this version.

### Changed
- **REPL cold start** — startup banner uses `assess_setup_status_fast()` (no `resolve_model` on boot).
- **Busy composer** — unified slash dispatch while a turn is running; live activity preview on the toolbar during bash/jobs.
- **Resource use** — session rewrite on compact (not append-only snapshots); bounded `read` (256 KB / 400 lines); TTL cache LRU caps; discovery/slash/skills cache limits; job registry prune (24 h finished); checkpoint cap (5); repo-map walk capped at 600 files.
- **Application run state** — `ApplicationRunService` tracks run transitions from loop events; `after_prepare` hook fired from runtime.
- **Test suite** — ~320 focused tests (down from ~540); merged `test_util`, `test_ui_basics`, `test_cli_misc`, `test_agent_loop`, `test_agent_runtime`, `test_repl_misc`; removed redundant/trivial modules.
- **Docs** — removed stale `docs/adr/`, `docs/superpowers/`, `cli-ux.md`, `ideal-cli-spec.md`, `kite-0.9-architecture-program.md`; updated references in AGENTS, README, architecture, CONTEXT, kite_commands.
- **CI** — `pytest` and `kite bench --check` on every push/PR; release verify script checks bench gate.

### Fixed
- **Streaming TUI** — busy composer no longer restarts on every agent event; hints use toolbar flash instead of scrollback spam.
- Provider retry countdown in the running line; compaction start/end render in the transcript.
- Status tail rendering aligned with `format_status_tail` expectations in tests.
- `compaction_end` always emitted after `compaction_start`.

## [0.9.4] - 2026-09-07

### Added
- **`/live`** — toggle real-time bash and background-job output in the REPL (`SessionUiState.live_terminal`).
- **Auto venv** — `discover_venv()` + `prepare_child_env()` prepend project `.venv`/`venv` to bash `PATH` when `pyvenv.cfg` is present (`[environment] auto_venv` in config).
- Execution context prompt line documents detected `python_venv`.

### Changed
- Bash output routes through `tool_output` / `job_output` events when a subscriber is attached (Rich TUI); stderr fallback for headless runs.

### Fixed
- (Includes all fixes shipped on main since v0.9.3: guardrails, SSRF, REPL responsiveness, approval composer keys, token defaults, agent/persistence reliability, CI gates.)

## [0.9.3] - 2026-09-06

### Fixed
- **False "work complete" on task requests** — assistant replies like `Hey! 👋` no longer auto-submit; only the **user's** casual turn (hi/thanks/short Q&A) may end in text-only submit.
- Footer **running line** clears on `agent_end` so idle chrome does not show `working · 1 task` after completion.

### Changed
- System prompt + `CONTEXT.md` + `kite_commands.md` document the completion decision table (user intent vs model reply).
- `_is_casual_user_turn` recognizes `hi kite` and task keywords (`test`, `lower`, `can you`, …).

## [0.9.2] - 2026-09-06

### Added
- **Opt-in durable memory** — MEMORY.md and episodic notes inject only when the user asks (`/remember`, `/memory`, or `[memory] inject = "always"`).
- **Working-state continuity** — compact/budget-continue briefs inject separately from durable memory; no auto-pin to MEMORY.md.
- **Daily-driver loop** — unverified edits get verify nudges instead of idle stall; blocked submit includes suggested verification command; fuzzy `edit` fallback; compaction preserves edited paths.
- **Web tools overhaul** — `webfetch` returns extracted readable text (title, metadata, JSON pretty-print); DuckDuckGo redirect unwrapping; search dedupe + HTML parser fallback; private-network URL blocking; `tests/test_web.py`.
- **Composer `@` completion** — `@path` attach tokens complete like `/attach` (word-boundary `@`, skips email addresses).
- **Persistent verification badge** — footer shows live `verification_status` (e.g. `unverified edits`) during runs.

### Changed
- System prompt clarifies memory is not instructions unless loaded.
- **`webfetch`** consolidated into `web.py` (shared fetch/extract with `webcrawl`); no longer returns raw HTML soup by default.
- **`websearch`** tries GET lite fallback when HTML POST fails; unwraps tracking URLs from DuckDuckGo/Google.
- Approval toolbar shows **`[a]/[n]/[q]`** keys during prompts instead of queue/steer hints; composer placeholder switches to approval keys.
- **80% cost warnings** flash on the toolbar while the busy composer is pinned (no scrollback jump).
- Failed tool rows show **collapsed multi-line errors** (same collapse as bash output).
- Flash notes on the footer **expire after 8s** so stale messages do not linger.
- **`Tab`** explicitly cycles slash and `@` completions; **Enter** always sends the line.

### Fixed
- Approval wait no longer counts as idle no-tool turns.
- Relative cache deletes on Windows stay out of mandatory approval in auto/yolo.

## [0.9.1] - 2026-09-06

### Added
- **Interactive budget floors** — chat uses ~80 steps / $10 when on package defaults; honor explicit lower user caps.
- **Budget auto-continue** — up to 2 resumes on `LimitsExceeded` with unfinished work + continuity brief; inbox queue wins.
- **Continuity memory** — Codex/Pi-style briefs (mission / done / next / todos) after compact and before budget continue; episodic store + prompt inject.
- **Structured `submit` tool** — preferred completion path with `message` (Done / Changed / Verification); legacy bash marker still supported.
- **Repo map** — `context/repomap.py` injects Aider-style symbol sketch; git-changed files ranked first.
- **ToolExecutor production cutover** — agent loop routes tools through `PolicyEngine` + `ToolExecutor` by default.
- **Live verification UX** — `verification_status` events update footer during runs; `submit_blocked` when claims outrun evidence.
- **Replay acceptance** — `ReplayBundle.events` + `acceptance` criteria for transcript-level eval without live providers.
- **EvidenceVerifier wiring** — bash check commands feed evidence ledger; summary included in verification payload.

### Changed
- Default `compaction_ratio` **0.80 → 0.75** (auto-checkpoint remains ~72%).
- `LimitsExceeded` / `TimeExceeded` render as soft pauses with continue hints (not hard error spam).
- Documentation refreshed for adaptive budget, continuity, and busy composer chrome (`kite_commands.md`).

### Fixed
- `/compact` (and other zero-arg slash handlers) no longer raise `TypeError` when dispatch passes an empty arg.
- WaitSpinner no longer wipes the pinned busy composer; activity updates the toolbar instead.
- Status toolbar no longer crashes on pending approval (`bits` → `parts`).

## [0.9.0] - 2026-09-04

### Added
- **Application layer** — `RunSpec`, `EventEnvelope`, `ApplicationRunService`, `HarnessDependencies` (`src/kite/application/`). Existing `Harness` is a compatibility adapter; production CLI/REPL still use it.
- **Context assembler** — `ContextItem` / `ContextBudget` / `ContextSnapshot` with provenance, source budgets, and untrusted-content delimiters.
- **Policy and execution seams** — `PolicyEngine`, `ToolExecutor`, `ProcessRunner`, `ChangeJournal` (restore without `git reset --hard` on the journal itself).
- **SQLite event store** — WAL append/load/redact/resume reconstruction (`SQLiteEventStore`). JSONL sessions remain the production store.
- **ModelGateway** — typed provider error categories, retries, `BudgetLedger` (subagent cost counted once).
- **EvidenceVerifier** — verification from tool results, not model claims.
- **CLI/REPL contracts** — `CliResult` exit codes, `ReplEventReducer` (adapters; live REPL still projects legacy events).
- **Recorded replay** — `kite.eval.ReplayBundle` runs without live providers.
- **CI** — Linux and Windows × Python 3.11 and 3.12; ruff on the application layer.
- **Busy composer** — pinned prompt while a turn runs; Enter queues; `/tasks`; footer tok/s and cache hit.
- **Skill library links** — `/skills add ./path` (or an absolute folder) **symlinks** into `~/.kite/skills` (Windows directory junction if a symlink is refused); project `.kite/skills/<name>` points at the global copy. Restricted mode may **read** that library (and symlink targets); writes stay sandboxed. Reinstall unlinks; it does not delete the real tree.

### Changed
- Milestone docs describe adapters as **landed**, not full production cutover.
- Packaged execution mode stays **host**; `PolicyEngine` defaults to restricted when used as the new seam.
- Sibling-prefix path checks are separator-aware; host mode does not clamp to the workspace (protected paths still blocked).

### Fixed
- ChangeJournal reports a conflict when the user deletes a file the agent wrote, instead of rewriting it.
- `BudgetLedger.total_cost()` no longer double-counts subagent usage.

## [0.8.2] - 2026-09-02

### Added
- **JobRegistry** - unified background bash (ackground=true) and live subagents; /jobs, /kill [id|all], kill-on-quit; footer jobs N.
- **Busy composer** - Esc/Ctrl+C//stop, Ctrl+G//steer, Enter queues; busy chrome on footer/composer; main-thread SIGINT.
- **Left-bar pickers** - numbered TTY menus for approve/theme/skills/sessions/models and related CLI flows.
- **Bundled skills** - /orchestrate, /research, /pr.
- **SYSTEM.md / APPEND_SYSTEM.md** - project or user system prompt replace/append.
- **Package scripts** - scripts/pkg.sh / pkg.ps1 update|reinstall|uninstall.

### Changed
- Plan/build handoff - plan writes checklist + risks; build continues the list.
- Thinking traces expanded by default; mouse capture off by default; clipboard shortcuts in composer.
- Submit gate blocks narrated done without a recorded passing check.

### Fixed
- BYOS login opens browser + left-bar device/code flow; interactive select/setup polish.
## [0.8.1] - 2026-09-01

### Added
- **`kite login`** — CLI for BYOK (hidden API key, double-entry for new keys) and BYOS OAuth (`chatgpt`, `claude`, `grok`).
- **`kite dashboard`** — per-user session analytics: tools, tokens, cache, cost, attention queue (`--session`, `--json`, `--watch`).
- **`--long` task mode** — higher step/cost limits, phase checkpoints, `mode_long.md` for multi-hour work.
- **Context7 docs tools** — built-in `context7_resolve` / `context7_docs` (optional `CONTEXT7_API_KEY`); session UTC/local time in system prompt.
- **Token-efficient tools** — bash-first inspection; lean `read`; plan-mode read-only bash via `is_inspection_bash()`.
- **UI polish** — unified approval panel; terminal-style bash cards; thinking collapsed by default (`/expand-thinking`, Ctrl+T); colourful task progress strip.
- **Provider retry/continue** — exponential backoff on transient faults; session preserved (`kite resume <id>`).
- **`load_kite_env()`** — project `.env` first; `~/.kite/.env` fills unset/empty keys (fixes `.env.example` placeholders).
- **BYOK login UX** — validation, permission warnings, masked key fingerprints in `/keys` and success messages.
- **Mandatory approval** — high-risk bash (sudo, rm, installs, git writes, curl, …) always prompts; no yolo/auto/trust bypass.
- **Agent completion** — no early submit; idle nudges; stop on tool errors with logs.
- **Git approval split** — `git status`/`log`/`diff` auto-allow; `git add`/`commit`/`push` always gated.
- **Memory `ForgetResult`** — `/forget` and `memory` tool report removed notes **and** episodes.
- **Tool arg repair** — malformed model tool JSON repaired before execution (`models/tool_args.py`).

### Changed
- **Setup wizard** — BYOK vs BYOS paths; OAuth during setup; credential-ready banner.
- **Provider picker** — BYOK/BYOS labels, auth state (`linked`, `key set`, `login required`).
- **`/help`** — canonical slash list + **legacy aliases** section (`/select` → `/model select`, etc.).
- **Memory prompt** — slimmer injection; semantic `MEMORY.md` + episodic sqlite.
- **LiteLLM retries** — `num_retries=0` when agent loop handles `provider_max_retries`.
- **Anti-bloat** — dead code removed; GitHub tools off by default; trimmed prompts.

### Fixed
- **REPL `/keys`** — OAuth shows `linked` / `login required`, not `missing oauth`.
- **Duplicate provider fault UI** — `agent_end` no longer re-renders after `provider_fault`.
- **Credential env loading** — empty project `KEY=` no longer blocks `~/.kite/.env` keys.

## [0.8.0] - 2026-09-01

### Added
- **BYOS (Bring Your Own Subscription)** — OAuth login for ChatGPT/Codex, Claude, and Grok via `kite keys --set <provider>` or `/login` in the REPL; dynamic model lists from subscription APIs (`src/kite/providers/byos.py`).
- **Approval modes** — `yolo` (no prompts), `auto` (auto inside workspace, ask outside), `supervised` (reads free; all mutations need approval); aliases on CLI and `/approve`.
- **Submit gate** — blocks `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` when edits lack passing test/lint artifacts, tests failed, or summary claims success without evidence.
- **Verification hardening** — progress-aware loop guard (reset on changed output, hard-stop at 5 repeats), post-edit verification nudges, broader test-command detection.
- **Token optimizations** — 80% compaction ratio, fast deterministic compaction below 92% context, summary-aware observation elision (8k default), tool-pair-safe compaction tail.
- **Durable session events** — JSONL event stream alongside transcript messages.
- **Subagent timeout** — configurable `orchestrator_timeout_seconds` (default 300s).
- **`api_styles` config** — per-provider route hint (`chat` | `messages` | `responses`) on `ResolvedModel`.
- **BYOK model picker** — radiolist TUI for API-key providers; subscription providers skip live picker after OAuth.

### Changed
- Default `max_bash_output_chars` lowered to 32k; `system.md` trimmed with token-aware peek guidance and evidence-first verifiability rules.
- `mode_build.md` documents harness submit blocking and required `## Verification` section.

### Fixed
- Circular import in `config/readiness.py` when loading OAuth provider modules.

## [0.7.2] - 2026-08-31

### Added
- **`/restricted on|off`** (alias `/sandbox`) — REPL toggle for path sandbox; **off by default** (host mode).
- **Slash menu scroll** — mouse wheel and scroll-key bindings on the `/` completion dropdown.
- **Compaction ctx meter** — `/compact` and auto-compaction refresh the footer context bar immediately.

### Removed
- **MCP integration** — stdio MCP client and `[[mcp]]` runtime config removed; use `Harness.extra_tools` for custom tools.

### Changed
- **Default execution mode** — `host` instead of `restricted` in runtime TOML and guardrail defaults; use `/restricted on` for a tighter sandbox.
- **Runtime assembly** — merged extra-tool wiring; audit listener registered once; cached `UserConfig` and bundled prompts.

### Fixed
- **Bare `kite` launch** — `readiness` used `os.stdin.isatty()`; now routes through `sys.stdin`.
- **`set_cwd` outside repo** — sessions can move to Desktop or sibling dirs; sandbox follows execution cwd (protected paths still blocked).

## [0.7.1] - 2026-08-31

### Added
- **Tool cards UI** — structured tool rows (`▸ read  path`), parallel batch headers, read line-count summaries, stream coalescing for less flicker.
- **Setup readiness** — `config/readiness.py`; first-run prompt on bare `kite`; REPL `/setup` wizard; `kite providers` / `kite keys` show ready/not-ready status.
- **Install `--setup`** — `./scripts/install.sh --setup` and `install.ps1 -Setup` run the wizard after install (TTY only).
- **`kite help`** — grouped quick reference CLI map; slimmer `/help` builtins with legacy aliases preserved.

### Changed
- **CI** — pytest on every push and PR to `main` (Python 3.11 + 3.12); isolated `KITE_HOME` + `KITE_SKIP_SETUP` in CI.
- Provider picker sorts configured and recommended providers (groq, openrouter, ollama) first.
- Install scripts point new users at `kite setup` instead of editing `.env` manually.

### Fixed
- `UserConfig.path` property for setup wizard config display.

## [0.7.0] - 2026-08-31

### Added
- **`kite bench`** — repeatable harness timing (CLI import, config, context, tools, prompt assembly) with `--json`, `--save`, and `--compare` for BEFORE/AFTER deltas.
- **`set_cwd` tool** — session execution cwd separate from project root; file tools and bash resolve relative paths from execution cwd.
- **`[guardrails] execution_mode`** — `restricted` (default sandbox) or `host` (broader filesystem access; protected paths still blocked).
- **`ToolResult` contract** — structured tool outcomes and scheduling metadata (`tools/metadata.py`).
- **Parallel read-only tools** — safe fan-out for concurrent `read`/`grep`/`glob`/`ls` in one model turn.
- **Bash cancellation** — Ctrl+C / interrupt propagates to long-running bash subprocesses (`CancelToken`).
- **Context checkpoints** — auto snapshot at ~72% context; `/checkpoint save|list|restore|show` in the REPL.
- **`/handoff`** — export `.kite/handoff-<session>.md` + `.json` for another agent or machine.
- **Preserved-fact compaction** — shared `run_compaction()` path; facts block survives summarization.
- **Lazy REPL init** — defer `resolve_model` until first task; reuse `Harness` across turns when config unchanged.
- **Bundled `/handoff` prompt**; expanded `system.md`, mode/role prompts, and install scripts.
- **`scripts/bump_release.sh`** — version bump + CHANGELOG stub + annotated tag helper.

### Changed
- Guardrails follow live execution cwd; host mode allows explicit external paths when configured.
- System prompt documents execution context, structured finish format (Done/Changed/Verification), and session continuity.
- Install scripts bootstrap `~/.kite/` (including `checkpoints/`), support `--verify` / `-Verify` for post-install pytest.
- Docs refresh: `CONTEXT.md`, `kite_commands.md`, `AGENTS.md`, `architecture.md`, design specs.

### Fixed
- Missing `HarnessSlots` / `HookBus` imports in `agent/runtime.py` after merge.

## [0.6.8] - 2026-08-30

### Fixed
- Long-running `bash` tools stream output live instead of appearing hung until exit.
- Slow tools emit `tool_progress` heartbeats; model API calls honor a 180s timeout.
- Default `bash_timeout_seconds` raised to 120s.
- CI commit-count job handles rebased/force-pushed batches; pytest runs via `uv run`.

## [0.6.7] - 2026-08-30

### Added
- `kite setup` and `kite keys` onboarding with hidden API key input to `~/.kite/.env`.
- REPL `/login`, `/logout`, `/keys`, and `/select` for credentials and model selection.
- Keyboard shortcuts: Ctrl+O expand tools, Ctrl+P plan, Ctrl+B build, Ctrl+S status.
- `/thinking` and `/fast` level menus when the provider advertises both effort modes.
- Maintainer-only `kite maintainer dashboard` (requires `KITE_MAINTAINER_KEY`).
- `CONTEXT.md` and `AGENTS.md` for agent-readable repo guidance.
