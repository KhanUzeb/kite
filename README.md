<h1 align="center">Kite</h1>

<p align="center">
  A terminal-first coding agent for local repositories
</p>

<p align="center">
  <a href="https://github.com/KhanUzeb/kite/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/KhanUzeb/kite/tests.yml" alt="CI status">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  </a>
  <a href="CHANGELOG.md">
    <img src="https://img.shields.io/badge/version-1.0.0-cyan.svg" alt="Version">
  </a>
  <a href="https://www.python.org">
    <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  </a>
</p>

<p align="center">
  Plan, build, review, and automate work across local repositories.
</p>

**Version:** 1.0.0

**Keywords:** coding agent, AI code assistant, terminal coding assistant, agent CLI, SWE-agent style loop, repository automation, code review automation

## Why Kite

Working in a terminal on a real repository means juggling plans, edits, tests, and reviews across many tools. Kite puts that loop in one place: describe the task, watch it inspect code, apply guarded edits, and verify the result — without leaving your shell or handing your repo to a black box.

## Highlights

- **Plan then build** — read-only checklist first (`/plan`), edits when you say so (`/build`)
- **Multi-provider** — OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and OpenAI-compatible endpoints
- **Guarded tools** — sandboxing, approval modes, secret redaction, and verification gates on `submit`
- **Memory that persists** — sessions, checkpoints, handoffs, and project notes that survive restarts

## Quick start

```bash
# macOS / Linux / WSL (public repo; private → git clone fallback in script help)
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
cd ~/projects/my-app && kite
kite setup   # guided API key + model picker on first run
```

```powershell
# Windows (ExecutionPolicy bypass if needed — see Setup)
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex
```

## Example

```bash
kite run "explain this repo"
kite run --mode plan "how should we add auth?"
# in the REPL:
/fix flaky login test
/plan
/build
```

## Table of contents

- [Why Kite](#why-kite)
- [Highlights](#highlights)
- [Quick start](#quick-start)
- [Example](#example)
- [Features](#features)
- [Setup](#setup)
- [Use Kite on any project](#use-kite-on-any-project)
- [Tests](#tests)
- [CLI](#cli)
- [Architecture](#architecture)
- [Design docs](#design-docs)

## Features

- **Tight agent loop** — a mini-swe-agent style sync loop (query → tools → observe → repeat) with budgeted turns and resumable sessions.
- **Multi-provider** — LiteLLM-backed model resolution across OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and OpenAI-compatible endpoints.
- **Real coding tools** — read, write, edit, bash, grep, glob, ls, `set_cwd`, **`submit`** (structured completion), web fetch/search/crawl, todo tracking, and a `subagent` orchestrator.
- **Evidence-first verification** — artifact-aware checks per workspace package; `submit` blocked without passing verification; live `verification_status` in the footer.
- **0.9 execution pipeline** — production loop routes tools through `PolicyEngine` + `ToolExecutor` (guardrails still enforce bash denylist inside tools).
- **Repo map** — Aider-style symbol sketch in project context; git-changed files ranked first.
- **Execution context** — separate project root vs session cwd; `restricted` or `host` execution mode; parallel safe read-only tools.
- **Context lifecycle** — preserved-fact compaction, auto-checkpoints at ~72% context, `/checkpoint` restore, `/handoff` export; **repo map** symbols for faster orientation in large trees.
- **Harness benchmarks** — `kite bench` for repeatable startup/context/tool timing (no live LLM).
- **Headless tasks** — `kite tasks run` for JSONL/plain-text batches; `kite run --headless` for CI/cloud agents with structured stderr logging.
- **Skills & plugins** — `SKILL.md` packs (npm, npx, GitHub, or a **local path symlink** into `~/.kite/skills`), prompt commands, plugins, and `.kite/extensions/` for custom tools.
- **Guardrails** — path sandboxing, bash danger checks, recursive secret redaction, process-tree teardown on timeout, SSRF-safe HTTP tools, and per-session approval modes (`auto` / `approve` / `trust` / `readonly`).
- **Session privacy** — `session_persistence = "redacted"` (default) sanitizes transcripts before write; `full` or `disabled` via `kite config` or `/privacy sessions`.
- **Skill trust** — bundled skills are trusted; npm/git/project skills are labeled untrusted with provenance metadata.
- **Global identity memory** — `~/.kite/memory/USER.md`, `PROFILE.md`, `WORKING.md` (always global, never per-repo); injected as soft untrusted context when present.
- **Subagent orchestration** — bundled personas + custom `~/.kite/subagents/*.md` (`kite subagents --init`, `/agents init`), `profile`/`role` dispatch, `/agents` crew board, `/live agents` streaming.
- **Rich TUI** — streaming, collapsed tool blocks, live plan checklist, write/edit diff previews, git-stat diffs, theme/font switching, and a context-usage meter.
- **Portable** — install once, then run `kite` from any project directory via `--cwd`.

## Setup

### Quick install (global — works anywhere on your machine)

Install once per user. Puts `kite` on your PATH. Then open any folder and run it — no project clone, no `.venv` activate.

**Recommended — bootstrap scripts** (install `uv` if needed, then `uv tool install` from **GitHub only**, not PyPI):

```bash
# macOS / Ubuntu / Linux / WSL
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
curl -fsSL .../download.sh | bash -s -- --setup    # run kite setup after install
curl -fsSL .../download.sh | bash -s -- -- --force # reinstall global CLI
```

```powershell
# Windows
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex
```

If ExecutionPolicy blocks PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex"
```

Requires the GitHub repo to be **public** for `raw.githubusercontent.com`. On 404 (private repo), the scripts print exact **git clone** or **uv tool install git+…** fallbacks (`KITE_REPO_SLUG`, `KITE_BRANCH`, `KITE_REPO_URL` override the default `KhanUzeb/kite`).

Needs: `curl`/`irm` + `git` (macOS: `xcode-select --install`; Ubuntu: `sudo apt-get install -y curl git`).

**Manual (uv + git only):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.12 --force "git+https://github.com/KhanUzeb/kite.git"
uv tool update-shell
```

Then from **any** directory:

```bash
cd ~/projects/my-app    # or C:\dev\my-app
kite
```

Update: `uv tool upgrade kite` · Uninstall: `uv tool uninstall kite`

### Contributor install (optional)

Only if you are developing kite itself:

```bash
git clone https://github.com/KhanUzeb/kite.git && cd kite
./scripts/install.sh --dev          # still puts kite on PATH (editable)
# .\scripts\install.ps1 -Dev
```

### Manual global install

```bash
uv tool install "git+https://github.com/KhanUzeb/kite.git"
uv tool update-shell
```

### First run

```bash
kite setup                    # guided API key + model picker (recommended)
kite providers                # or check keys manually
kite models -p groq --select
```

Or edit keys manually:

```bash
# Copy .env.example to .env (or ~/.kite/.env) and set your key(s)
kite keys                     # show which keys are set
kite keys --set groq          # paste a key into ~/.kite/.env
kite web-keys set tavily      # optional paid websearch (also: exa, firecrawl)
kite keys --set firecrawl     # same storage path as web-keys set
kite login codex              # BYOS: ChatGPT/Codex via openai-codex SDK
kite login claude             # BYOS: Claude Code CLI (claude auth login)
kite login grok               # BYOS: Grok CLI (or kite login xai)
kite login antigravity      # BYOS: Google subscription via agy CLI (calls need GEMINI_API_KEY)
kite logout codex             # unlink BYOS subscription
kite models -p groq --select
kite models -p zen --select          # OpenCode Zen (OPENCODE_API_KEY)
kite models -p go --select           # OpenCode Go
kite models -p nvidia --select       # NVIDIA NIM (NVIDIA_API_KEY)
kite runtime-config
```

**REPL shortcuts:** `Ctrl+O` expand tool output · `Ctrl+P` plan · `Ctrl+B` build · `Ctrl+S` status · type `/` for commands

### Use Kite on any project 

Install once (global). After that `kite` is a normal system command for your user — any drive, any folder.

1. **`cd` into the project.** Workspace = that directory.
2. Run `kite` / `kite chat` / `kite run "…"`.

```bash
cd ~/projects/my-app
kite
kite run "add error handling"
```

If `kite` is missing after install, open a **new** terminal (PATH was updated). Or: `uv tool update-shell`.

To work on a directory **without** changing shell cwd, pass `--cwd`:

```bash
kite run --cwd ~/projects/my-app "review auth module"
kite chat --cwd C:\dev\other-repo
kite context --cwd .
```

Global config, sessions, and identity memory live in `~/.kite/` (`USER.md`, `PROFILE.md`, `WORKING.md`, `MEMORY.md` under `memory/`). Per-project overlays (optional): `.kite/commands`, `.kite/plugins`, `.kite/MEMORY.md` for project-scoped facts only.

## Tests

```bash
pytest                    # guardrails, agent, sessions, git-stat diffs, skills, UI helpers
pytest -v                 # verbose
```

Coverage is a compact ~150-test suite: guardrails/SSRF, approval, agent loop, sessions, verification, orchestrator, credentials/BYOS, CLI/REPL, and `PolicyEngine`/`ToolExecutor`. It is not a full integration suite against live LLM APIs. See `tests/README.md`.

```bash
python scripts/sync_version.py --check
ruff check src tests
pytest -q
kite bench --check
```

**CI:** GitHub Actions (`.github/workflows/tests.yml`) runs `sync_version.py --check`, `ruff check src tests`, `pytest -q`, and `kite bench --check` on Linux and Windows × Python 3.11 and 3.12. Details in [CONTRIBUTING.md](CONTRIBUTING.md#ci-github-actions).

## CLI

Interactive (plan/build, slash commands, live plan, diffs, approval):

```bash
kite                         # REPL, prompt is ready immediately
kite chat --mode plan
kite chat --approval approve
```

One-shot:

```bash
kite run "explain this repo"
kite run --mode plan "how should we add auth?"
kite run --mode build --approval approve "add tests"
kite run -p groq -m llama-3.3-70b-versatile "add tests" -v
kite run "/commit"
kite run "/skill:debug flaky login test"
kite resume <session-id>
kite resume <session-id> "also update the README"
```

In the REPL: start in **build** mode — type a task. `/plan` for an opt-in read-only checklist. `/help` for commands · `/agents profiles` · Ctrl+C interrupts the turn. Shortcuts: Ctrl+B build · Ctrl+P plan · Ctrl+O expand · F2 status.

Approval modes: `auto` · `approve` · `trust` · `readonly`. Set `KITE_LOADER=grid|dots|orbit|wave|spin` for terminal loader style.

Visual walkthrough: [`guide.md`](guide.md) · Full command map: [`kite_commands.md`](kite_commands.md)

Other commands:

```bash
kite sessions
kite sessions --show <session-id>
kite sessions --delete <session-id>
kite sessions --delete-all -y
kite skills --show commit
kite skills --add @scope/pkg
kite skills --add ./my-skill          # symlink into ~/.kite/skills
kite commands
kite plugins
kite memory
kite memory --remember "prefer ruff"
kite context
kite runtime-config
kite setup                    # first-run: key + model wizard
kite login [provider]         # BYOK key or BYOS subscription
kite logout [provider]        # unlink BYOS subscription
kite keys [--set provider]    # show or paste API keys (hidden); also tavily|exa|firecrawl
kite web-keys [set|logout]    # optional paid web tool keys → ~/.kite/.env
kite keys --logout provider   # remove a stored BYOK/web key or BYOS session
kite providers
kite models -p groq
kite models --select
kite config
kite config --select-model
kite bench [--json] [--save PATH] [--compare BASELINE.json]   # harness timing (no LLM)
kite tasks init | kite tasks run <file.jsonl>                 # headless task batches
kite run --headless "task"                                    # non-TTY stderr event log
kite subagents [--show id] [--init id]                        # subagent personas
```

Command map: [kite_commands.md](kite_commands.md)

Install on a new machine: curl/irm one-liner (global CLI) or `scripts/install.sh --dev` for contributors. See [Setup](#setup).

Home: `~/.kite/` (`sessions/`, `trajectories/`, `configs/`, `commands/`, `skills/`, `plugins/`, `memory/`, `catalog.toml`, `config.toml`, `.env`). Project overlays: `.kite/commands`, `.kite/plugins`, `.kite/memory`.

## Architecture

Overview: **[architecture.md](architecture.md)** — layers, lifecycle, context/compaction, extension points.

```
CLI → ApplicationRunService (0.9 adapter) → AgentRuntime → DefaultAgent loop
         │                                      │
    ├ config/                            ├ PolicyEngine → ToolExecutor → tools
    ├ prompts/                           ├ compaction + verification collector
    ├ skills/                            └ sessions / trajectory / replay
    ├ providers/
    └ context/ (+ repomap)
```

## Design docs

Canonical markdown:

- [`architecture.md`](architecture.md): system overview — layers, lifecycle, memory, extension points
- `CONTEXT.md`: domain glossary (terms agents and humans share)
- `AGENTS.md`: how to hack on this repo (map, conventions, tests)
- [`docs/RELEASE-1.0.0.md`](docs/RELEASE-1.0.0.md): latest release notes
- [`CHANGELOG.md`](CHANGELOG.md): version history

```
src/kite/
  application/             # 0.9 contracts as modules: execution, policy, tools, verification, …
  agent/                   # loop, runtime, harness, mode, events, exceptions
  cli/                     # argparse entry, slash index
  ui/                      # Rich TUI (loaders, chips, context meter)
  config/                  # ~/.kite prefs + runtime TOML
  tools/coding.py
  providers/
  context/                 # discovery, repomap (git-ranked symbols), workspace
  memory/
  skills/ commands/ plugins/   # plugins/extensions.py loads .kite/extensions
  eval.py                  # ReplayBundle + acceptance criteria (no live LLM)
  tasks.py                 # kite tasks / --headless batches
scripts/                   # install + download (unix/win), sync_version.py, bump_release.sh
tests/                     # pytest suite (~150 tests, no live LLM)
```
