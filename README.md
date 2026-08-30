# Kite

A slim hybrid coding-agent harness: the **mini-swe-agent** control flow plus **tau**-style tools, providers, context, sessions, skills, and guardrails.

[![Tests](https://github.com/KhanUzeb/kite/actions/workflows/tests.yml/badge.svg)](https://github.com/KhanUzeb/kite/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-0.6.6-cyan.svg)](CHANGELOG.md)

**Version:** 0.6.6

## Features

- **Tight agent loop** — a mini-swe-agent style sync loop (query → tools → observe → repeat) with budgeted turns and resumable sessions.
- **Multi-provider** — LiteLLM-backed model resolution across OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and OpenAI-compatible endpoints.
- **Real coding tools** — read, write, edit, bash, grep, glob, ls, web fetch/search/crawl, todo tracking, and a `subagent` orchestrator.
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
# Copy .env.example to .env (or ~/.kite/.env) and set your key(s)
kite providers
kite models -p groq --select
kite models -p zen --select          # OpenCode Zen (OPENCODE_API_KEY)
kite models -p go --select           # OpenCode Go
kite models -p nvidia --select       # NVIDIA NIM (NVIDIA_API_KEY)
kite runtime-config
```

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

Coverage focuses on guardrails, approval/trust, loop detection, session I/O, verification, MCP warnings, orchestrator dispatch, and status/chip renderers. It is not a full integration suite against live LLM APIs.

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

In the REPL: `/plan` `/build` `/undo` `/expand` `/collapse` `/thinking` `/fast` `/effort` `/theme` `/font` `/attach` `/clip` `/skills` `/skills add` `/commit` `/explain` `/commands` `/plugins` `/memory` `/help`. Type `/` for the command menu. User skills show `~`. Ctrl+C stops the current turn.

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
kite providers
kite models -p groq
kite models --select
kite config
kite config --select-model
```

UX notes: `docs/cli-ux.md` · spec coverage: `docs/ideal-cli-spec.md` · command map: `kite_commands.md`

Install on a new machine: `scripts/install.sh` (macOS/Linux) or `scripts/install.ps1` (Windows). See [Setup](#setup).

Home: `~/.kite/` (`sessions/`, `trajectories/`, `configs/`, `commands/`, `skills/`, `plugins/`, `memory/`, `catalog.toml`, `config.toml`, `.env`). Project overlays: `.kite/commands`, `.kite/plugins`, `.kite/memory`.

## Architecture

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
  data/prompts/{system,instance}.md
  data/commands/{explain,fix,pr}.md
  data/skills/{commit,debug,test,review}/SKILL.md
```
