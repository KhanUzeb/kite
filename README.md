# Kite

A slim hybrid coding-agent harness: the **mini-swe-agent** control flow plus **tau**-style tools, providers, context, sessions, skills, and guardrails.


[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-0.7.1-cyan.svg)](CHANGELOG.md)

**Version:** 0.7.1

## Features

- **Tight agent loop** — a mini-swe-agent style sync loop (query → tools → observe → repeat) with budgeted turns and resumable sessions.
- **Multi-provider** — LiteLLM-backed model resolution across OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and OpenAI-compatible endpoints.
- **Real coding tools** — read, write, edit, bash, grep, glob, ls, `set_cwd`, web fetch/search/crawl, todo tracking, and a `subagent` orchestrator.
- **Execution context** — separate project root vs session cwd; `restricted` or `host` execution mode; parallel safe read-only tools.
- **Context lifecycle** — preserved-fact compaction, auto-checkpoints at ~72% context, `/checkpoint` restore, `/handoff` export for other agents.
- **Harness benchmarks** — `kite bench` for repeatable startup/context/tool timing (no live LLM).
- **Skills & plugins** — `SKILL.md` packs (installable from npm, npx, or GitHub), prompt commands, and plugins.
- **Guardrails** — path sandboxing, bash danger checks, secret redaction, and per-session approval modes (`auto` / `approve` / `trust` / `readonly`).
- **Rich TUI** — streaming, collapsed tool blocks, live plan checklist, git-stat diffs, theme/font switching, and a context-usage meter.
- **MCP-native** — stdio MCP servers become regular tools.
- **Portable** — install once, then run `kite` from any project directory via `--cwd`.

## Setup

### Quick install (any workstation)

Clone and run the install script once. It creates a venv, installs Kite in editable mode, and seeds `~/.kite/.env` from `.env.example` if needed.

**macOS / Linux**

```bash
git clone https://github.com/KhanUzeb/kite.git
cd kite
./scripts/install.sh
```

Or download and install in one step (installs to `~/kite` by default):

```bash
curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/KhanUzeb/kite.git
cd kite
.\scripts\install.ps1
```

Or:

```powershell
irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
```

Custom location: `KITE_INSTALL_DIR=~/tools/kite ./scripts/install.sh` or `.\scripts\install.ps1 -Dir C:\tools\kite`.

### Manual install

```bash
uv venv --python 3.12
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
uv pip install -e ".[dev]"
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
kite models -p groq --select
kite models -p zen --select          # OpenCode Zen (OPENCODE_API_KEY)
kite models -p go --select           # OpenCode Go
kite models -p nvidia --select       # NVIDIA NIM (NVIDIA_API_KEY)
kite runtime-config
```

**REPL shortcuts:** `Ctrl+O` expand tool output · `Ctrl+P` plan · `Ctrl+B` build · `Ctrl+S` status · type `/` for commands

### Use Kite on any project (not just this repo)

Install Kite once (script or manual install above). After that you do **not** need to be inside the kite checkout.

1. **Activate the venv** (or add its `bin` / `Scripts` folder to your `PATH` — the install script prints the exact path).
2. **`cd` into the project you want to work on.** Kite uses your current directory as the workspace (tools, git status, `.kite/` overlays, `AGENTS.md`, etc.).
3. Run `kite`, `kite chat`, or `kite run "…"` from there.

```bash
cd ~/projects/my-app
kite                          # REPL in my-app
kite run "add error handling"
```

To work on a directory **without** changing shell cwd, pass `--cwd`:

```bash
kite run --cwd ~/projects/my-app "review auth module"
kite chat --cwd C:\dev\other-repo
kite context --cwd .
```

Global config and sessions live in `~/.kite/`. Per-project overlays (optional) go in the target repo: `.kite/commands`, `.kite/plugins`, `.kite/memory`.

## Tests

```bash
pytest                    # guardrails, agent, sessions, git-stat diffs, skills, UI helpers
pytest -v                 # verbose
```

Coverage focuses on guardrails, approval/trust, loop detection, session I/O, verification, MCP warnings, orchestrator dispatch, reasoning/setup UX, and status/chip renderers. It is not a full integration suite against live LLM APIs.

**CI:** GitHub Actions runs `pytest` when a push or PR to `main` contains **5+ commits** in the batch; smaller pushes skip. Run locally before every PR, or trigger **Actions → Tests → Run workflow** manually. Details in [CONTRIBUTING.md](CONTRIBUTING.md#ci-github-actions).

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

In the REPL: `/help` for commands · `/plan` `/build` `/model select` `/checkpoint` `/handoff` · Ctrl+C interrupts the turn. Shortcuts: Ctrl+O expand · Ctrl+P plan · Ctrl+B build · Ctrl+S status.

Approval modes: `auto` · `approve` · `trust` · `readonly`. Set `KITE_LOADER=grid|dots|orbit|wave|spin` for terminal loader style.

Full command map: [`kite_commands.md`](kite_commands.md)

Other commands:

```bash
kite sessions
kite sessions --show <session-id>
kite sessions --delete <session-id>
kite sessions --delete-all -y
kite skills --show commit
kite skills --add @scope/pkg
kite commands
kite plugins
kite memory
kite memory --remember "prefer ruff"
kite context
kite runtime-config
kite setup                    # first-run: key + model wizard
kite keys [--set provider]    # show or paste API keys (hidden)
kite keys --logout provider   # remove a stored key
kite providers
kite models -p groq
kite models --select
kite config
kite config --select-model
kite bench [--json] [--save PATH] [--compare BASELINE.json]   # harness timing (no LLM)
```

UX notes: `docs/cli-ux.md` · spec coverage: `docs/ideal-cli-spec.md` · command map: `kite_commands.md`

Install on a new machine: `scripts/install.sh` (macOS/Linux) or `scripts/install.ps1` (Windows). See [Setup](#setup).

Home: `~/.kite/` (`sessions/`, `trajectories/`, `configs/`, `commands/`, `skills/`, `plugins/`, `memory/`, `catalog.toml`, `config.toml`, `.env`). Project overlays: `.kite/commands`, `.kite/plugins`, `.kite/memory`.

## Architecture

Overview: **[architecture.md](architecture.md)** — layers, lifecycle, context/compaction, extension points.

```
CLI → AgentRuntime → DefaultAgent loop
         │               │
    ├ config/       ├ compaction
    ├ prompts/      ├ tools (+ guardrails)
    ├ skills/       └ sessions / trajectory
    ├ providers/
    └ context/
```

## Design docs

Canonical markdown:

- [`architecture.md`](architecture.md): system overview — layers, lifecycle, memory, extension points
- `CONTEXT.md`: domain glossary (terms agents and humans share)
- `AGENTS.md`: how to hack on this repo (map, conventions, tests)
- `docs/kite-system-design.md`: architecture, atlas, tradeoffs
- `docs/cli-ux.md`: plan/build TUI, style guide, render loop
- `kite_commands.md`: CLI, REPL slashes, skills, plugins, tools

Generated PDFs (gitignored): `docs/kite-system-design.pdf`, `docs/cli-ux.pdf`, `docs/ideal-cli-spec.pdf`, `docs/kite_commands.pdf`

```bash
uv pip install fpdf2
python scripts/build_design_pdf.py
```

```
src/kite/
  agent/                   # loop, runtime, harness, mode, events, exceptions
  cli/                     # argparse entry, slash index
  ui/                      # Rich TUI (loaders, chips, context meter)
  config/                  # ~/.kite prefs + runtime TOML
  tools/coding.py
  providers/
  context/
  memory/
  skills/ commands/ plugins/
  mcp/                     # stdio MCP client
scripts/
  install.sh install.ps1   # clone + venv + editable install (any workstation)
tests/                     # pytest suite
  data/configs/default.toml
  data/prompts/{system,instance,mode_*,role_*}.md
  data/commands/{explain,fix,pr,handoff}.md
  data/skills/{commit,debug,test,review}/SKILL.md
```
