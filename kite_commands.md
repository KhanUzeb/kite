# Kite commands

Quick reference for the CLI, REPL slashes, and agent tools. **Human git commits stay yours** — Kite checkpoints are for undo/handoff only.

Prefix `//` if a user message must start with `/`.

---

## Surfaces

| Surface | Examples | Hits the model? |
|---------|----------|-----------------|
| **CLI** | `kite run`, `kite sessions` | Only `run` / `chat` / `resume` |
| **REPL control** | `/plan`, `/model select`, `/checkpoint` | Never |
| **Prompt slashes** | `/commit`, `/explain`, `/handoff` | Yes — becomes the next turn |
| **Tools** | `read`, `edit`, `bash`, … | Yes — model calls them |

Run **`kite help`** for the CLI map. In the REPL type **`/help`**.

---

## CLI essentials

```bash
kite                         # REPL (same as kite chat)
kite run "add tests"         # one-shot
kite resume <id> [message]   # continue

kite setup                   # first-run wizard
kite keys --set groq         # API keys → ~/.kite/.env
kite models -p groq --select
kite sessions [--show id]
kite bench [--json]          # harness timing (no LLM)
```

**Common flags** (`run` / `chat` / `resume`): `-p` provider · `-m` model · `--cwd` · `--mode plan|build` · `--approval auto|approve|trust|readonly` · `-v` · `--attach PATH`

**Housekeeping** (no model): `kite providers` · `kite config` · `kite context` · `kite skills` · `kite commands` · `kite plugins` · `kite memory` · `kite runtime-config`

**Advanced**: `kite apply` · `kite import` · `kite exec` · `kite audit` · `kite cloud`

Install: `scripts/install.sh` / `install.ps1` — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## REPL control (`/help`)

### Chat

| Command | What |
|---------|------|
| `/plan` `/p` | Read-only checklist |
| `/build` `/b` | Apply edits |
| `/approve auto\|approve\|readonly` | Session autonomy |
| `/compact` | Summarize older turns |
| `/checkpoint save\|list\|restore\|show` | Transcript snapshots |
| `/handoff [dir]` | Export for another agent |
| `/undo` | Revert last kite: git checkpoint |
| `/clear` `/new` | Fresh chat |
| `/expand` | Toggle tool output (`/collapse` still works) |
| `/status` | Mode, model, cost, session (`/cost` → same) |
| `/session list\|show\|open\|delete` | Transcripts |
| `/resume <id>` | Open session |
| `/init` | Write `KITE.md` |
| `/theme` `/font` | UI prefs |

### Model & keys

| Command | What |
|---------|------|
| `/model` | Show current model |
| `/model list <provider>` | Live model ids (`/models` alias) |
| `/model select [provider]` | Interactive picker (`/select` alias) |
| `/model provider/id [--save]` | Set model (`/provider` alias for provider only) |
| `/login` `/keys` `/logout` | Credentials |
| `/reasoning auto\|off\|fast\|thinking` | Effort (`/effort`, `/thinking`, `/fast`) |

### Memory & extensions

| Command | What |
|---------|------|
| `/memory [semantic\|episodic]` | Notes (`/semantic`, `/episodic`) |
| `/remember` `/forget` | Add or drop notes |
| `/skills [add pkg\|name]` | Skill packs |
| `/commands` `/plugins` | Markdown prompts & plugins |
| `/attach` `/clip` `/detach` | Next-turn attachments |

**Shortcuts**: Ctrl+O expand · Ctrl+P plan · Ctrl+B build · Ctrl+S status · Ctrl+C interrupt turn

---

## Prompt slashes (skills & commands)

Bundled: `/explain` · `/fix` · `/pr` · `/handoff` · skills `/commit` `/debug` `/review` `/test`

Overlay order (later wins): bundled → `~/.kite/commands` → plugins → `.kite/commands`

---

## Agent tools

**Plan mode**: `read` `grep` `glob` `ls` `set_cwd` `task` `webfetch` `websearch` `webcrawl` `skill` `memory` `todo_*`

**Build mode**: all tools + `write` `edit` `bash` `subagent`

`set_cwd` — session working directory for file tools and bash (separate from project root).

---

## Paths

| Path | Purpose |
|------|---------|
| `~/.kite/` | Config, keys, sessions, checkpoints, skills |
| `<repo>/.kite/` | Project commands, plugins, handoff files |
| `~/.kite/checkpoints/` | Context snapshots (not git) |
| `.kite/handoff-*` | Agent handoff brief + JSON |

**Git checkpoint** (`kite:` commit, `/undo`) ≠ **context checkpoint** (`/checkpoint restore`).
