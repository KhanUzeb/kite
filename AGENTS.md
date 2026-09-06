# AGENTS.md — Working on the Kite repository

Instructions for coding agents (Cursor, Claude Code, Kite itself, etc.) hacking **this** repo. Domain vocabulary: [CONTEXT.md](CONTEXT.md).

---

## What this repo is

**Kite** v0.9.3 — Python 3.11+ package (`src/kite/`). Slim hybrid harness:

- **Engine:** mini-swe-agent style loop (`agent/loop.py`) — query → tools → observe → repeat
- **Cockpit:** tau-inspired assembly — catalog providers, skills, guardrails, Rich TUI, JSONL sessions

Stack: LiteLLM, Rich, prompt_toolkit, pydantic, tomllib. Entry: `kite.cli.run:main`.

---

## Repo map (where to change what)

```
src/kite/
  application/    RunSpec, ApplicationRunService, EventEnvelope (0.9 contracts)
  agent/          Loop, harness, runtime, compaction, cancel, tool_result, orchestrator
  bench/          Repeatable harness benchmarks (`kite bench`)
  cli/            argparse entry (run.py), slash index, setup, stats, bench, import/apply
  config/         ~/.kite/config.toml (UserConfig), runtime TOML merge
  context/        Project discovery, workspace/execution cwd, token estimate
  providers/      Catalog, resolve model, list_models, credentials, select
  models/         LiteLLM wrapper, reasoning effort, prompt cache
  tools/          Coding tools (read/write/edit/bash/set_cwd/…), jobs registry, metadata, web, github
  guardrails/     Path sandbox, execution mode, bash policy, secret redaction
  ui/             REPL, render, approval, complete, theme, status
  memory/         Sessions JSONL, checkpoints, handoff, compaction_ops, semantic/episodic
  eval/           Recorded replay (ReplayBundle) without live providers
  skills/         SKILL.md loader; npm/git install; local path symlink into ~/.kite/skills
  commands/       Markdown slash prompt loader
  plugins/        .kite/plugins discovery
  extensions/     .kite/extensions loader (register_tool → Harness.extra_tools)
  data/           Bundled catalog.toml, prompts, skills, commands
tests/            pytest unit tests (no live LLM)
docs/             Design + UX specs (source of truth for behavior)
scripts/          install.sh, install.ps1, build_design_pdf.py
```

**Layer rule:** CLI/UI subscribe to events; `ApplicationRunService` (0.9) or `AgentRuntime` assembles; `DefaultAgent` loops; tools/guardrails execute. Do not import UI from `agent/` or call LiteLLM from `ui/repl.py` directly.

---

## Dev setup

```bash
./scripts/install.sh          # macOS/Linux
# .\scripts\install.ps1       # Windows
pytest                        # always run before PRs
pytest -v tests/test_foo.py   # single file
```

Editable install: `uv pip install -e ".[dev]"`. Config and keys live in **`~/.kite/`** (not this repo). Never commit `.env` or real API keys.

---

## Tests & CI

- **Local:** `pytest` from repo root (uses `tests/`, `conftest.py` isolates `KITE_HOME`).
- **CI:** `.github/workflows/tests.yml` runs pytest on every push and PR to `main` (Python 3.11 + 3.12). See [CONTRIBUTING.md](CONTRIBUTING.md).

Add tests for real behavior; skip trivial “assert True” coverage. No live provider calls in unit tests.

---

## Conventions

1. **Small diffs** — Match surrounding style; one concern per change.
2. **Data over code** — Prefer `data/catalog.toml`, markdown prompts, TOML config over new Python constants.
3. **Slash builtins** — Register in `ui/commands.py`; handle in `ui/repl.py`; completion in `ui/complete.py`.
4. **New CLI subcommands** — `cli/run.py` `build_parser()` + handler module.
5. **Provider behavior** — `providers/` + `models/reasoning.py`; don’t hardcode model id lists.
6. **Secrets** — `providers/credentials.py` writes `~/.kite/.env` with owner-only perms; never log key values.
7. **Docs** — User-facing behavior changes need `kite_commands.md` and/or `docs/cli-ux.md`. Glossary changes → `CONTEXT.md`. Prompt changes → `data/prompts/system.md`. Project/user overrides: `.kite/SYSTEM.md` / `APPEND_SYSTEM.md` (same idea as pi / Prime Agent).

---

## Key flows (for debugging)

| User action | Start here |
|-------------|------------|
| `kite` REPL | `ui/repl.py` → `agent/harness.py` |
| `kite run "…"` | `cli/run.py` `cmd_run` |
| `/login groq` | `providers/credentials.py` → `ui/repl.py` |
| Model resolution | `providers/resolve.py` |
| Tool execution | `env/local.py` + `tools/coding.py` + `tools/jobs.py` + `guardrails/` |
| 0.9 tool pipeline | `application/execution/pipeline.py` (`ToolExecutor`) + `application/policy/engine.py` |
| Context compaction | `agent/compaction.py` + `memory/compaction_ops.py` |
| Repo map / discovery | `context/repomap.py` + `context/discovery.py` |
| Verification / submit gate | `agent/verification.py` + `application/verification/` |
| Replay / eval | `eval/replay.py` (`ReplayBundle` + acceptance) |
| Checkpoints / handoff | `memory/context_checkpoint.py` + `memory/handoff.py` + `ui/repl.py` |
| Benchmarks | `bench/` + `cli/bench.py` |
| Streaming UI | `ui/render.py` `RunDisplay` ← `agent/events.py` |
| Slash expansion | `cli/slash.py` `CommandIndex` |

---

## Commands cheat sheet (this repo)

```bash
kite setup                      # onboarding wizard
kite keys --set groq            # save API key (hidden)
kite models -p groq --select    # pick default model
kite chat                       # REPL
kite bench                      # harness timing baseline
pytest -q                       # verify changes
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
| [docs/kite-0.9-architecture-program.md](docs/kite-0.9-architecture-program.md) | 0.9 seams, adapter status, CI matrix |
| [docs/adr/0001-application-harness-seam.md](docs/adr/0001-application-harness-seam.md) | Why `ApplicationRunService` exists |
| [docs/RELEASE-0.9.0.md](docs/RELEASE-0.9.0.md) | 0.9 release notes |
| [docs/cli-ux.md](docs/cli-ux.md) | REPL cells, footer, shortcuts, approval UX |
| [docs/ideal-cli-spec.md](docs/ideal-cli-spec.md) | Feature coverage checklist |
| [kite_commands.md](kite_commands.md) | CLI/REPL command reference |
| [CONTEXT.md](CONTEXT.md) | Term definitions |

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
./scripts/bump_release.sh 0.9.0   # bump, sync README/AGENTS/docs, CHANGELOG stub, tag
# edit CHANGELOG.md + docs/RELEASE-0.9.0.md
git push origin main --tags       # tag push runs .github/workflows/release.yml
```

- **`scripts/sync_version.py`** — sync or `--check` (also runs in CI on every push/PR). Stamps `scripts/*` via `# kite-release-version:`.
- **`scripts/verify_release_pr.sh`** — pre-tag pytest + version check on main.
- **`.github/workflows/release.yml`** — on `v*` tag push, verify stamps and publish GitHub release from `docs/RELEASE-X.Y.Z.md`.
