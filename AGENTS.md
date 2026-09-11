# AGENTS.md — Working on the Kite repository

Instructions for coding agents (Cursor, Claude Code, Kite itself, etc.) hacking **this** repo. Domain vocabulary: [CONTEXT.md](CONTEXT.md).

---

## What this repo is

**Kite** v0.9.7 — Python 3.11+ package (`src/kite/`). Slim hybrid harness:

- **Engine:** mini-swe-agent style loop (`agent/loop.py`) — query → tools → observe → repeat
- **Cockpit:** tau-inspired assembly — catalog providers, skills, guardrails, Rich TUI, JSONL sessions

Stack: LiteLLM, Rich, prompt_toolkit, pydantic, tomllib. Entry: `kite.cli.run:main`.

---

## Repo map (where to change what)

```
src/kite/
  application/    0.9 contracts + flattened modules (execution, policy, tools, verification, cli, …)
  agent/          Loop, harness, harness_build, runtime, compaction, cancel, tool_result, orchestrator
  bench/          Repeatable harness benchmarks (`kite bench`)
  tasks.py        Headless task batches (`kite tasks`, `--headless`)
  cli/            argparse entry (run.py), slash index, setup, stats, bench, tasks, import/apply
  config/         ~/.kite/config.toml (UserConfig), runtime TOML merge
  context/        Project discovery, workspace/execution cwd, token estimate
  providers/      Catalog, resolve model, list_models, credentials, select
  models/         LiteLLM wrapper, reasoning effort, prompt cache
  tools/          Coding tools (read/write/edit/bash/…), web + web_providers (Tavily/Exa/Firecrawl), jobs, github
  guardrails/     Path sandbox, execution mode, bash policy, secret redaction
  ui/             REPL, render, approval, complete, theme, status
  memory/         Sessions JSONL, checkpoints, handoff, compaction_ops, semantic/episodic, user_context, working_style, secure_io
  data/subagents/ Bundled subagent personas (scout, reviewer, shell, coder, context)
  cli/subagents.py  kite subagents list/show/init; REPL /agents profiles|show|init
  eval.py         Recorded replay (ReplayBundle) without live providers
  skills/         SKILL.md loader; npm/git install; local path symlink into ~/.kite/skills
  commands/       Markdown slash prompt loader
  plugins/        .kite/plugins discovery + extensions loader (register_tool → Harness.extra_tools)
  data/           Bundled catalog.toml, prompts, skills, commands
tests/            compact pytest suite (~150 tests, no live LLM; see tests/README.md)
docs/             current RELEASE notes only (`docs/RELEASE-X.Y.Z.md`)
scripts/          install.sh, install.ps1, download.sh, download.ps1, sync_version.py, bump_release.sh
```

**Layer rule:** CLI/UI subscribe to events; `ApplicationRunService` (0.9) or `AgentRuntime` assembles; `DefaultAgent` loops; tools/guardrails execute. Do not import UI from `agent/` or call LiteLLM from `ui/repl.py` directly.

---

## Dev setup

```bash
./scripts/install.sh --dev    # macOS/Linux editable checkout
# .\scripts\install.ps1 -Dev  # Windows
# curl …/install.sh | bash    # end-user: global CLI via uv tool (any dir)
pytest                        # always run before PRs
pytest -v tests/test_foo.py   # single file
```

Editable install: `uv pip install -e ".[dev]"` (or `./scripts/install.sh --dev`). End-user global CLI: `uv tool install "git+…"`. Config and keys live in **`~/.kite/`** (not this repo). Never commit `.env` or real API keys.

---

## Tests & CI

- **Local:** `pytest` from repo root (uses `tests/`, `conftest.py` isolates `KITE_HOME`).
- **CI:** `.github/workflows/tests.yml` runs pytest on every push and PR to `main` (Python 3.11 + 3.12). See [CONTRIBUTING.md](CONTRIBUTING.md).

Add tests for real behavior in the matching `tests/test_*.py` domain module. Combine related asserts; skip one-assert slop. No live provider calls. Target size is ~150 collected tests.

---

## Conventions

1. **Small diffs** — Match surrounding style; one concern per change.
2. **Data over code** — Prefer `data/catalog.toml`, markdown prompts, TOML config over new Python constants.
3. **Slash builtins** — Register in `ui/commands.py`; handle in `ui/repl.py`; completion in `ui/complete.py`.
4. **New CLI subcommands** — `cli/run.py` `build_parser()` + handler module.
5. **Provider behavior** — `providers/` + `models/reasoning.py`; don’t hardcode model id lists.
6. **Secrets** — `providers/credentials.py` writes `~/.kite/.env` with owner-only perms; never log key values.
7. **Docs** — User-facing behavior changes need `kite_commands.md`. Glossary and memory-layer terms → `CONTEXT.md`. Layer/architecture changes → `architecture.md`. Prompt changes → `data/prompts/system.md`. Security behavior → `SECURITY.md`. Project/user overrides: `.kite/SYSTEM.md` / `APPEND_SYSTEM.md` (same idea as pi / Prime Agent).

---

## Key flows (for debugging)

| User action | Start here |
|-------------|------------|
| `kite` REPL | `ui/repl.py` → `agent/harness.py` |
| `kite run "…"` | `cli/run.py` `cmd_run` |
| `kite run --headless` / `kite tasks run` | `tasks.py` + `cli/tasks.py` |
| `/login groq` | `providers/credentials.py` → `ui/repl.py` |
| Model resolution | `providers/resolve.py` |
| Tool execution | `env/local.py` + `tools/coding.py` + `tools/jobs.py` + `guardrails/` |
| 0.9 tool pipeline | `application/execution.py` (`ToolExecutor`) + `application/policy.py` |
| Context compaction | `agent/compaction.py` + `memory/compaction_ops.py` |
| Repo map / discovery | `context/repomap.py` + `context/discovery.py` |
| Verification / submit gate | `agent/verification.py` + `application/verification.py` |
| Replay / eval | `eval.py` (`ReplayBundle` + acceptance) |
| Custom Python tools | `plugins/extensions.py` + `.kite/extensions/` |
| Checkpoints / handoff | `memory/context_checkpoint.py` + `memory/handoff.py` + `ui/repl.py` |
| User identity memory | `memory/user_context.py` — global `USER.md` / `PROFILE.md` |
| Subagent personas | `agent/subagent_profiles.py` + `data/subagents/*.md` + `~/.kite/subagents/` |
| `kite subagents` / `/agents init` | `cli/subagents.py` + `ui/repl.py` `_slash_agents` |
| Orchestrator / crew | `agent/orchestrator.py` + `tools/jobs.py` + `/agents` `/live agents` |
| Benchmarks | `bench/` + `cli/bench.py` |
| Streaming UI | `ui/render.py` `RunDisplay` ← `agent/events.py` |
| Slash expansion | `cli/slash.py` `CommandIndex` |

---

## Commands cheat sheet (this repo)

```bash
kite setup                      # onboarding wizard
kite keys --set groq            # save API key (hidden)
kite web-keys set tavily        # optional websearch (also: exa, firecrawl)
kite models -p groq --select    # pick default model
kite chat                       # REPL
kite bench                      # harness timing baseline
kite tasks run tasks.jsonl      # headless batch (JSONL or plain text)
kite run --headless "task"      # single headless run with stderr event log
pytest -q                       # verify changes
pytest tests/test_bench.py -q   # harness timing budgets
kite bench --check              # same budgets from CLI
```

Full map: [kite_commands.md](kite_commands.md).

Maintainer-only (requires `KITE_MAINTAINER_KEY` in `~/.kite/.env`): `kite maintainer dashboard`.

---

## Anti-patterns

- Importing Rich or prompt_toolkit inside `agent/loop.py`
- Storing API keys in repo or printing them in logs
- Breaking sandbox: allowing **writes** outside the workspace (global skill **reads** under `~/.kite/skills` are a documented exception)
- Adding Textual/full-screen TUI without an explicit design decision
- Changing default prompts to wrap casual chat (`hi`) as “solve this task” — chat stays literal
- Skipping `pytest` when touching guardrails, sessions, approval, or render
- Running with `--no-guardrails` on untrusted tasks (disables path/bash/secret protections)

---

## Architecture docs (read when touching those areas)

| Doc | Use when |
|-----|----------|
| [architecture.md](architecture.md) | Layers, lifecycle, extension points |
| [kite_commands.md](kite_commands.md) | CLI/REPL command reference |
| [CONTEXT.md](CONTEXT.md) | Term definitions |
| [docs/RELEASE-0.9.7.md](docs/RELEASE-0.9.7.md) | Current version release notes |

---

## Project overlays (when testing Kite on sample apps)

Users run Kite from **any** directory. This repo is the harness source; when dogfooding here, workspace = repo root. Optional per-repo files: `KITE.md`, `.kite/commands/`, `.kite/plugins/`.

---

## Commit / PR notes

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Conventional short commits (`feat(ui): …`, `fix(guardrails): …`). Update docs when behavior changes. Do not commit `LICENSE`/`CHANGELOG` churn unless asked.

---

## Release automation

Version source of truth: **`pyproject.toml`**. Stamped files stay in sync via `scripts/sync_version.py`.

```bash
./scripts/bump_release.sh 0.9.7   # bump, sync README/AGENTS/docs, CHANGELOG stub, tag
# edit CHANGELOG.md + docs/RELEASE-0.9.7.md
git push origin main --tags       # tag push runs .github/workflows/release.yml
```

- **`scripts/sync_version.py`** — sync or `--check` (also runs in CI on every push/PR). Stamps `scripts/*` via `# kite-release-version:`.
- **`.github/workflows/release.yml`** — on `v*` tag push, verify stamps and publish GitHub release from `docs/RELEASE-X.Y.Z.md`.
