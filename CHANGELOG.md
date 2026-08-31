# Changelog

All notable changes to Kite are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1] - 2026-08-31

### Added
- **Tool cards UI** — structured tool rows (`▸ read  path`), parallel batch headers, read line-count summaries, stream coalescing for less flicker.
- **Setup readiness** — `config/readiness.py`; first-run prompt on bare `kite`; REPL `/setup` wizard; `kite providers` / `kite keys` show ready/not-ready status.
- **Install `--setup`** — `./scripts/install.sh --setup` and `install.ps1 -Setup` run the wizard after install (TTY only).
- **`kite help`** — grouped quick reference CLI map; slimmer `/help` builtins with legacy aliases preserved.

### Changed
- **CI** — pytest runs on every pull request; isolated `KITE_HOME` + `KITE_SKIP_SETUP` in CI; `install-smoke` job validates install script.
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
- CI workflow: pytest on push/PR batches with 5+ commits.

### Changed
- Nemotron and other reasoning models detected via name heuristic when API metadata is empty.
- Project context discovery loads `CONTEXT.md` alongside `AGENTS.md`.

## [0.6.6] - 2026-08-30

### Added
- Skill packs: install from npm, npx, or GitHub `owner/repo` into `~/.kite/skills` (`kite skills --add`, `skills/install.py`).
- UI themes and fonts: `/theme` (auto, kite, dark, light, dim, mono) and `/font` (unicode, ascii), persisted in `~/.kite`.
- Git-stat `+N,-M` counts shown on write/edit diffs and the plan checklist.

### Changed
- Lazy CLI imports for a cheaper REPL cold start.
- Provider catalog and runtime config now support user overlays.
- `kite run` accepts `--cwd` to target a directory other than the shell's working directory.

## [0.6.5] - 2026-08-29

### Added
- Initial public-facing harness: mini-swe-agent loop, tau-style tools/providers/skills/guardrails, Rich TUI, sessions, and memory.
- Multi-provider model resolution via LiteLLM (OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and more).
- Approval modes (`auto` / `approve` / `trust` / `readonly`) and plan/build modes.
- MCP stdio client, subagent orchestrator, and trajectory import from Cursor/Claude/Aider/Codex.
