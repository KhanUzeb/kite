# Kite

Slim hybrid coding-agent harness: **mini-swe-agent** control flow + **tau**-style tools, providers, context, sessions, skills, and guardrails.

**Version:** 0.6.5

## Setup

```bash
uv venv --python 3.12
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
uv pip install -e ".[dev]"
```

```bash
# Copy .env.example → .env (or ~/.kite/.env) and set your key(s)
kite providers
kite models -p groq --select
kite models -p zen --select          # OpenCode Zen (OPENCODE_API_KEY)
kite models -p go --select           # OpenCode Go
kite models -p nvidia --select       # NVIDIA NIM (NVIDIA_API_KEY)
kite runtime-config
```

## Tests

```bash
pytest                    # 32 tests — guardrails, agent, sessions, UI helpers
pytest -v                 # verbose
```

Coverage focuses on guardrails, approval/trust, loop detection, session I/O, verification, MCP warnings, orchestrator dispatch, and status/chip renderers. Not a full integration suite against live LLM APIs.

## CLI

Interactive (plan/build, slash commands, live plan, diffs, approval):

```bash
kite                         # REPL — prompt is ready immediately
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

In the REPL: `/plan` `/build` `/undo` `/expand` `/collapse` `/thinking` `/fast` `/effort` `/attach` `/clip` `/skills` `/commit` `/explain` `/commands` `/plugins` `/memory` `/help`. Type `/` for the command menu. Ctrl+C stops the current turn.

Approval modes: `auto` · `approve` · `trust` · `readonly`. Set `KITE_LOADER=grid|dots|orbit|wave|spin` for terminal loader style.

Full command map: [`kite_commands.md`](kite_commands.md)

Other commands:

```bash
kite sessions
kite sessions --show <session-id>
kite sessions --delete <session-id>
kite sessions --delete-all -y
kite skills --show commit
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

- `docs/kite-system-design.md` — architecture, atlas, tradeoffs
- `docs/cli-ux.md` — plan/build TUI, style guide, render loop
- `kite_commands.md` — CLI, REPL slashes, skills, plugins, tools

Generated PDFs (gitignored): `docs/kite-system-design.pdf`, `docs/cli-ux.pdf`

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
tests/                     # pytest suite
  data/configs/default.toml
  data/prompts/{system,instance}.md
  data/commands/{explain,fix,pr}.md
  data/skills/{commit,debug,test,review}/SKILL.md
```
