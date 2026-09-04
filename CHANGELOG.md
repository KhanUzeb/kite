# Changelog

All notable changes to Kite are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Structured `submit` tool** — preferred completion path with `message` (Done / Changed / Verification); legacy bash marker still supported.
- **Repo map** — `context/repomap.py` injects Aider-style symbol sketch; git-changed files ranked first.
- **ToolExecutor production cutover** — agent loop routes tools through `PolicyEngine` + `ToolExecutor` by default (`RuntimeOptions.use_tool_executor`).
- **Live verification UX** — `verification_status` events update footer during runs; `submit_blocked` when claims outrun evidence.
- **Replay acceptance** — `ReplayBundle.events` + `acceptance` criteria for transcript-level eval without live providers.
- **EvidenceVerifier wiring** — bash check commands feed evidence ledger; summary included in verification payload.

### Changed
- Documentation refreshed across `README.md`, `CONTEXT.md`, `architecture.md`, `kite_commands.md`, `docs/cli-ux.md`, and 0.9 program docs.

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
