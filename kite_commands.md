# Kite commands

Kite is a coding agent. **What lands in git is still yours.** Commands below are how you steer the process, not a second commit stream.

There are four surfaces:

| Surface | When | Hits the model? |
|---------|------|-----------------|
| **CLI** (`kite …`) | Outside a session, or to start one | Only `run` / `chat` / `resume` |
| **REPL slash** (`/…`) | Inside `kite` / `kite chat` | Control slashes never. Prompt slashes expand into the next turn. |
| **Markdown commands / skills / plugins** | `/explain`, `/commit`, `/skill debug`, plugin `/hello` | Yes — they become the user task |
| **Agent tools** | During a turn (`read`, `edit`, `bash`, …) | Yes — the model calls them |

Prefix `//` if you need a natural-language line that starts with `/`.

---

## 1. CLI

```
kite                         # REPL (same as kite chat)
kite --version
kite chat [--mode plan|build] [--approval auto|approve|trust|readonly] [--session id]
kite run "task"              # one-shot
kite resume <session-id>                 # open that transcript in chat
kite resume <session-id> [follow-up]     # one-shot continue
```

Shared flags on `run` / `chat` / `resume`:

| Flag | Meaning |
|------|---------|
| `-p` / `--provider` | Catalog name (`openai`, `anthropic`, `zen`, `go`, `nvidia`, …) |
| `-m` / `--model` | Model id within that provider |
| `--cwd` | Workspace |
| `--config` | Runtime TOML name or path |
| `--mode plan\|build` | Read-only checklist vs apply edits |
| `--approval auto\|approve\|trust\|readonly` | Default: `auto` for `run`, `approve` for chat |
| `--steps` `--cost` `--time` | Limits |
| `-v` / `-q` | Verbose tool bodies / quiet |
| `--no-context` `--no-compact` `--no-guardrails` | Opt out of injection, compaction, sandbox |
| `--attach PATH` | Attach a file or image (repeatable). Images route to a live vision model. |

Housekeeping (no model):

```
kite sessions [--limit N] [--show id] [--tail N]
kite sessions --delete <id> [<id> ...]
kite sessions --delete-all -y
kite providers
kite models [-p provider] [--select]
kite config [--set-provider …] [--set-model …] [--select-model] [--set-api-base …]
kite context [--json]
kite skills [--show name]
kite commands
kite plugins
kite memory [--remember text] [--forget query] [--project]
kite runtime-config [--config name]
```

You can also drop a path into the prompt with `@screenshot.png` or `@C:\path\spec.md`.

---

## 2. REPL control slashes

These never go to the model.

| Command | What it does |
|---------|----------------|
| `/plan` `/p` | Read-only mode, checklist |
| `/build` `/b` | Apply edits; approval stays unless it was readonly |
| `/approve auto\|approve\|trust\|readonly` | Autonomy for this session |
| `/model [provider/id]` | Show or set model |
| `/models [provider]` | List live models for the current (or named) provider |
| `/provider [name]` | Show or set provider |
| `/thinking` `/fast` | Effort: extended thinking, or low-latency (if the model supports it) |
| `/reasoning` `/effort auto\|off\|fast\|thinking` | Set effort; shown on the footer |
| `/undo` | Revert last **kite:** git checkpoint (agent edits only) |
| `/clear` `/new` | Fresh chat session (memory notes stay) |
| `/compact` | Summarize older turns now (OpenRouter free tier) |
| `/cost` | USD + context |
| `/status` | Mode, approval, model, cost, session id |
| `/session` | Current session id |
| `/sessions` `/session list` | Recent transcripts |
| `/session show [id]` | Print a transcript (current if omitted) |
| `/session open <id>` `/resume <id>` | Continue that chat |
| `/session delete [id\|all]` | Drop this (or another) transcript + trajectory |
| `/init` | Write `KITE.md` if missing |
| `/expand` | Toggle expanded tool output |
| `/collapse` | Collapse tool output (default) |
| `/trace` | Last traceback |
| `/skills [name]` | List skills, or print one |
| `/commands` | List markdown slash prompts |
| `/commands new name` | Write `.kite/commands/name.md` |
| `/plugins` | List plugins |
| `/plugins init name` | Scaffold `.kite/plugins/name` |
| `/memory [semantic\|episodic]` | Semantic markdown + episodic sqlite |
| `/semantic` | Show `MEMORY.md` notes |
| `/episodic` | Show sqlite episode log |
| `/remember [user\|project] text` | Append a note |
| `/forget id\|substring` | Drop matching notes |
| `/attach path` | Queue a file or image for the next turn (any path on disk) |
| `/clip` `/paste` `/clipboard` | Attach clipboard text or image |
| `/detach [name\|all]` | Drop queued attachments |
| `/attachments` | List queued files |
| `/help` `/h` | This map |
| `/quit` `/q` `/exit` | Leave the REPL |

Ctrl+C stops the **current turn**, not the process.

---

## 3. Prompt slashes (skills, markdown commands, plugins)

These **are** the next user turn. Overlay (later wins): bundled → `~/.kite/commands` → plugins → `.kite/commands`. Skills fill names that nothing else took. Builtins always win.

### Bundled commands (`data/commands/`)

| Command | Use |
|---------|-----|
| `/explain [path or question]` | Explain the repo or a focus |
| `/fix [test or error]` | Diagnose and patch a failure |
| `/pr [notes]` | Draft a PR title and body |

`$ARGUMENTS` (and `$1`…`$9`) in the markdown file is replaced with whatever you typed after the command.

### Bundled skills (`data/skills/`)

| Command | Same as |
|---------|---------|
| `/commit` | `/skill commit` or `/skill:commit` |
| `/debug` | `/skill debug` |
| `/review` | `/skill review` |
| `/test` | `/skill test` |

If a project command is also named `commit`, `/commit` runs the markdown file; `/skill:commit` still loads the skill.

### Add your own

```
# Project prompt  →  /ship
.kite/commands/ship.md

# User prompt     →  /ship  (unless the project file exists)
~/.kite/commands/ship.md

# Plugin
.kite/plugins/my-kit/plugin.toml
.kite/plugins/my-kit/commands/*.md
.kite/plugins/my-kit/skills/*/SKILL.md
```

Command file shape:

```markdown
---
name: ship
description: Cut a release
argument-hint: [tag]
---

Follow this playbook.

$ARGUMENTS
```

Scaffold from the REPL: `/commands new ship` · `/plugins init my-kit`.

List: `/commands` `/skills` `/plugins` or `kite commands` / `kite skills` / `kite plugins`.

---

## 4. Agent tools (model-called, not typed by you)

Plan mode: `read` `grep` `glob` `ls` `task` `webfetch` `websearch` `webcrawl` `skill` `memory` `todo_read` `todo_write`.

Build mode adds: `write` `edit` `bash`.

`memory` is notes (`list` / `remember` / `forget`), not the chat log. `KITE.md` / `AGENTS.md` are repo instructions; `/remember` is durable notes.

---

## 5. Where files live

```
~/.kite/
  config.toml          # default provider/model
  commands/*.md        # your slash prompts
  skills/*/SKILL.md
  plugins/<id>/
  memory/MEMORY.md     # semantic facts
  memory/episodes.sqlite
  sessions/*.jsonl
  approvals.json

<repo>/.kite/
  commands/*.md
  skills/
  plugins/
  memory/notes.jsonl
  MEMORY.md
```

Human commits are the source of truth for the project. Checkpoint `kite:` commits exist so `/undo` can revert agent edits without touching your own history.

---

## 6. Development

```bash
uv pip install -e ".[dev]"
pytest              # 32 tests
pytest -v
```

See `tests/` for guardrails, approval/trust, loop guard, sessions, verification, MCP, orchestrator, caches, and UI helpers.
