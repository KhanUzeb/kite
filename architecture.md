# Kite architecture

**Version:** 0.7.1 · Python 3.11+ · Entry: `kite.cli.run:main`

Kite is a **slim hybrid coding-agent harness**: a [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) style control loop wrapped in tau-inspired **runtime assembly** (providers, tools, guardrails, compaction, sessions). The brain never renders UI; the CLI never calls LiteLLM directly.

Deeper references: [docs/kite-system-design.md](docs/kite-system-design.md) (full atlas) · [docs/cli-ux.md](docs/cli-ux.md) (TUI) · [CONTEXT.md](CONTEXT.md) (glossary) · [AGENTS.md](AGENTS.md) (contributing)

---

## Design thesis

> **mini's loop is the engine; tau's assembly is the cockpit.**

| From mini-swe-agent | From tau (slimmed) |
|---------------------|-------------------|
| `Agent` / `Model` / `Environment` split | Typed tools + event stream |
| Linear `messages[]` trajectory | Provider catalog + config merge |
| `step = query → execute_actions` | Project context discovery |
| Exception exits (`Submitted`, limits) | Skills as `SKILL.md`, JSONL sessions |
| Cost / step / wall-time budgets | Context compaction + token accounting |

---

## Layer diagram

```
┌──────────────────────────────────────────────────────────────┐
│  CLI + UI          cli/run.py · ui/repl.py · ui/render.py     │
│  argparse, slash commands, Rich TUI, approval prompts        │
└────────────────────────────┬─────────────────────────────────┘
                             │  Event(kind, payload)
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Runtime assembly    agent/runtime.py · agent/harness.py     │
│  config merge · model resolve · tools · guardrails · session │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent loop          agent/loop.py (DefaultAgent)            │
│  compact → query → approve → execute → observe → repeat      │
└──────────────┬─────────────────────────────┬─────────────────┘
               │                             │
               ▼                             ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│  Model                   │   │  Environment                │
│  models/litellm_model.py │   │  env/local.py               │
│  LiteLLM + tool schemas  │   │  ToolRegistry → tools/*     │
└──────────────────────────┘   └─────────────────────────────┘
```

**Layer rule:** `agent/` must not import Rich or prompt_toolkit. `ui/` subscribes to events; `AgentRuntime` wires everything.

---

## Request lifecycle

1. **Parse** — `cli/run.py` builds args; REPL or one-shot task string.
2. **Assemble** — `AgentRuntime.run()` loads user + runtime TOML, resolves provider/model, gathers project context (`context/discovery.py`), builds tool registry (coding tools + optional MCP + GitHub).
3. **Prompt** — System prompt from `data/prompts/system.md` + project overlay (`AGENTS.md`, `KITE.md`, git status, tree). Instance prompt wraps the user task.
4. **Loop** — Each turn in `DefaultAgent`:
   - `_maybe_compact()` — shrink transcript if near context limit
   - `model.query(messages)` — streaming assistant + tool calls
   - `execute_actions()` — approval gate → `env.execute()` → observations appended
5. **Persist** — Messages append to `~/.kite/sessions/<id>.jsonl`; optional trajectory JSON; audit log entries.
6. **Render** — `RunDisplay` in `ui/render.py` maps events to chips, diffs, spinner, footer meter.

Exit paths: task submitted via bash magic line, step/cost/time limits, user interrupt (Ctrl+C), or unrecoverable format errors.

---

## Core modules

| Path | Responsibility |
|------|----------------|
| `agent/loop.py` | Main turn loop, approval, plan/build mode, tool execution |
| `agent/runtime.py` | One-shot assembly: model, env, session, summarizer, hooks |
| `agent/compaction.py` | Pre-query compaction gate (`LoopCompactor`) |
| `agent/events.py` | Thin event types (`tool_start`, `stream_delta`, `compact`, …) |
| `models/litellm_model.py` | LiteLLM adapter, streaming, reasoning effort, prompt cache |
| `providers/` | Catalog, resolve, credentials, live model listing |
| `tools/coding.py` | Built-in tools: read/write/edit/bash/grep/glob/ls/web/… |
| `guardrails/` | Path sandbox, bash deny patterns, secret redaction |
| `context/window.py` | Token estimate, `compact_messages`, deterministic summary |
| `context/discovery.py` | Workspace tree, git status, agent instruction files |
| `memory/session.py` | JSONL sessions + `compact_snapshot` + `context_checkpoint` audit rows |
| `memory/context_checkpoint.py` | Named transcript snapshots |
| `memory/handoff.py` | Handoff markdown + JSON export |
| `memory/compaction_ops.py` | Shared compaction + auto-checkpoint |
| `bench/` | `kite bench` timing suite |
| `skills/` | Load `SKILL.md` packs; install from npm/git |
| `mcp/client.py` | Stdio MCP servers → extra tools in registry |
| `ui/repl.py` | prompt_toolkit REPL, slash expansion, keybindings |

---

## Context & memory

Two separate systems:

**Project context (once per run)** — Injected into the system prompt: repo tree, git status, `AGENTS.md` / `KITE.md`, plus **execution context** (`project_root`, `execution_cwd`, `execution_mode`). Cached briefly; not re-summarized each turn.

**Transcript compaction (each turn)** — When estimated tokens ≥ `context_window - reserve` (default reserve 16k):

1. **Soft checkpoint** (~72% context) — auto-save full transcript to `~/.kite/checkpoints/<session>/` (once per size).
2. Keep the system message and a recent tail (~20k tokens from the end).
3. Extract **preserved facts** (constraints, errors, paths, tools) from dropped turns.
4. Summarize dropped middle turns (LLM via OpenRouter free tier, or deterministic fallback).
5. Inject a synthetic user message: `Previous conversation summary:` + facts block + summary.
6. Persist a `compact_snapshot` row in the session JSONL so `kite resume` continues from the compacted view.

**Manual:** `/compact` uses the same `run_compaction()` path as the loop. `/checkpoint save|restore` for named snapshots. `/handoff` exports `.kite/handoff-*` for another agent.

Config: `~/.kite/config.toml` — `auto_compact`, `compaction_*`, `[guardrails] execution_mode = restricted|host`.

---

## Configuration surfaces

| Location | Contents |
|----------|----------|
| `~/.kite/config.toml` | User prefs: default provider/model, theme, compaction, approval |
| `~/.kite/.env` | API keys (owner-only permissions) |
| `~/.kite/catalog.toml` | Provider/model catalog overlay |
| `src/kite/data/configs/default.toml` | Bundled runtime defaults (tools, guardrails, limits) |
| `.kite/commands/` | Project slash commands (markdown) |
| `.kite/plugins/` | Project plugin discovery |
| `AGENTS.md` / `KITE.md` | Per-repo agent instructions |

Runtime merge order: bundled defaults → user TOML → CLI flags.

---

## Tools & guardrails

Tools implement a common `Tool.run(args) → {ok, output, …}` contract. `LocalEnvironment.execute()` dispatches by name through `ToolRegistry`.

**Mutating tools** (`write`, `edit`, `bash`, …) pass through:

- **Plan mode** — blocked unless `/build` (todo_write still allowed)
- **Approval** — `auto` / `approve` / `trust` / `readonly`; preview diffs for write/edit
- **Guardrails** — paths clamped to workspace; bash deny patterns; secret write blocking

**MCP** — Declared in runtime TOML; stdio servers register additional tool schemas at startup.

**Subagent** — `subagent` tool spawns a bounded nested harness run; `task` is a lighter glob+grep fan-out.

---

## Event-driven UI

The agent emits events; the UI never polls internal state.

| Event | UI effect |
|-------|-----------|
| `stream_delta` / `stream_reasoning` | Live assistant text |
| `tool_start` / `tool_progress` / `tool_end` | Tool chips, spinner, collapsed output |
| `context` | Footer token meter |
| `compact` | Compaction notice (`↻ before → after`) |
| `checkpoint` | Context snapshot saved (`◇ checkpoint`) |
| `approval` | Inline approve/deny prompt |
| `todo` | Live plan checklist |

Streaming uses stderr for loaders; stdout stays clean for copy/paste.

---

## Extension points

| Want to… | Hook |
|----------|------|
| Add a CLI command | `cli/run.py` + handler module |
| Add a slash command | `ui/commands.py` + `ui/repl.py` + `ui/complete.py` |
| Add a tool | `tools/coding.py` or plugin; register in runtime config `[tools].enabled` |
| Add a provider | `data/catalog.toml` + credentials env var |
| Add a skill | `SKILL.md` in `~/.kite/skills` or `.kite/skills`; `/skills add` |
| Swap sandbox | Replace `env/local.py` (same `execute(action)` contract) |
| Override summarizer | `AgentRuntime` slot or `compaction_use_llm` in user config |

---

## Testing & CI

- **Local:** `pytest` from repo root (no live LLM calls; `KITE_HOME` isolated in fixtures).
- **CI:** `.github/workflows/tests.yml` — pytest on Python 3.11/3.12 when a push/PR batch has ≥5 commits; manual workflow dispatch always runs.

Focus areas: guardrails, approval, loop detection, sessions, render helpers, credentials, MCP warnings.

---

## Related docs

| Doc | Use when |
|-----|----------|
| [architecture.md](architecture.md) | Quick system overview (this file) |
| [docs/kite-system-design.md](docs/kite-system-design.md) | Full module atlas, tradeoffs, provider table |
| [docs/cli-ux.md](docs/cli-ux.md) | REPL cells, footer, shortcuts, approval UX |
| [docs/ideal-cli-spec.md](docs/ideal-cli-spec.md) | Feature coverage checklist |
| [kite_commands.md](kite_commands.md) | CLI/REPL command reference |
| [CONTEXT.md](CONTEXT.md) | Term definitions |
| [AGENTS.md](AGENTS.md) | Hacking on this repository |
