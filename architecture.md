# Kite architecture

**Version:** 1.0.7 · Python 3.11+ · Entry: `kite.cli.run:main`

Kite is a **slim hybrid coding-agent harness**: a [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) style control loop wrapped in tau-inspired **runtime assembly** (providers, tools, guardrails, compaction, sessions). 0.9 adds an **application layer** (`RunSpec`, `ApplicationRunService`, `PolicyEngine`, `ToolExecutor`) while `Harness` remains the compatibility adapter. The brain never renders UI; the CLI never calls LiteLLM directly.

Deeper references: [kite_commands.md](kite_commands.md) (CLI/REPL) · [CONTEXT.md](CONTEXT.md) (glossary) · [AGENTS.md](AGENTS.md) (contributing)

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
                             │  Event(kind, payload) / EventEnvelope
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Application (0.9)   application/service.py · contracts      │
│  RunSpec · ApplicationRunService · PolicyEngine · store    │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Runtime assembly    agent/runtime.py · agent/harness.py     │
│  config merge · model resolve · tools · guardrails · session │
│  build_tool_executor() → DefaultAgent.tool_executor          │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent loop          agent/loop.py (DefaultAgent)            │
│  compact → query → PolicyEngine → approve → ToolExecutor     │
│            → observe → verification_status → repeat          │
└──────────────┬─────────────────────────────┬─────────────────┘
               │                             │
               ▼                             ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│  Model                   │   │  Environment                │
│  models/litellm_model.py │   │  env/local.py               │
│  LiteLLM + tool schemas  │   │  ToolRegistry → tools/*     │
└──────────────────────────┘   └─────────────────────────────┘
```

**Layer rule:** `agent/` must not import Rich or prompt_toolkit. `ui/` subscribes to events; `ApplicationRunService` (0.9) or `AgentRuntime` wires everything.

`kite.ui` is a lightweight package, not a renderer facade: it no longer re-exports `RunDisplay`, `make_run_display`, `SessionUiState`, or `make_console`. The `make_run_display` factory is removed; construct `RunDisplay` from `kite.ui.render` directly. Import state from `kite.ui.state` and consoles from `kite.ui.style`. REPL startup defers prompt_toolkit/composer imports until needed.

---

## Request lifecycle

1. **Parse** — `cli/run.py` builds args; REPL or one-shot task string.
2. **Assemble** — `AgentRuntime.run()` loads user + runtime TOML, resolves provider/model, gathers project context (`context/discovery.py`), builds tool registry (coding tools + optional GitHub + `Harness.extra_tools` / `.kite/extensions`).
3. **Prompt** — System prompt from `data/prompts/system.md` + project overlay (`AGENTS.md`, `KITE.md`, git status, tree). Instance prompt wraps the user task.
4. **Loop** — Each turn in `DefaultAgent`:
   - `_maybe_compact()` — shrink transcript if near context limit
   - `model.query(messages)` — streaming assistant + tool calls; provider history is normalized so every tool call has exactly one adjacent result
   - `execute_actions()` — `PolicyEngine.authorize` → approval gate → **`ToolExecutor`** → `env.execute()` → observations appended; malformed result envelopes fail closed; **`verification_status`** events on state change
5. **Persist** — Messages append to `~/.kite/sessions/<id>.jsonl`; optional trajectory JSON; audit log entries.
6. **Render** — `RunDisplay` in `ui/render.py` maps events to chips, diffs, spinner, footer meter.

Exit paths: **`submit`** tool or bash submit marker, step/cost/time limits, user interrupt (Ctrl+C), submit blocked (verification), or unrecoverable format errors.

### Startup and request work

- Model resolution checks the configured default before probing subscription CLIs. `LitellmModel` construction does no capability-metadata lookup or network work; reasoning and parallel-tool capabilities are detected on the first relevant request and cached per instance. LiteLLM prewarming runs in the background while project context is assembled.
- Append-only history uses incremental token accounting. Prompt-cache preparation no longer memoizes whole transcripts with a lossy key: repeated tool output must not resend stale or missing turns, even when prompt caching is disabled.
- UI stream accumulation avoids repeated whole-buffer joins. Path completion uses `scandir` and a bounded top-40 selection; pickers cache filtered rows.


---

## Core modules

| Path | Responsibility |
|------|----------------|
| `agent/loop.py` | Main turn loop, approval, plan/build mode, **ToolExecutor** path |
| `agent/runtime.py` | One-shot assembly: model, env, session, summarizer, **build_tool_executor** |
| `agent/verification.py` | `VerificationCollector` — artifacts, plans, **EvidenceVerifier** |
| `application/execution.py` | **ToolExecutor** — authorize → run → normalize |
| `application/policy.py` | **PolicyEngine** — path/network authorization |
| `context/repomap.py` | Git-ranked symbol sketch for project context |
| `agent/compaction.py` | Pre-query compaction gate (`LoopCompactor`) |
| `agent/events.py` | Thin event types (`tool_start`, `stream_delta`, `compact`, …) |
| `models/litellm_model.py` | LiteLLM adapter, streaming with blocking fallback, reasoning effort, prompt cache |
| `providers/` | Catalog, resolve, credentials, live model listing, gateway key fallbacks, strict NIM parallel-tool gating |
| `tools/coding.py` | Built-in tools: read/write/edit/bash/grep/glob/ls/web/… |
| `guardrails/` | Path sandbox, bash deny patterns, secret redaction |
| `context/window.py` | Token estimate, `compact_messages`, deterministic summary |
| `context/discovery.py` | Workspace tree, git status, agent instruction files |
| `memory/session.py` | JSONL sessions + `compact_snapshot` + `context_checkpoint` audit rows |
| `memory/user_context.py` | Global `USER.md` / `PROFILE.md` injection |
| `memory/working_style.py` | `WORKING.md` + episodic `style` signals |
| `memory/secure_io.py` | Owner-only memory writes, length caps, untrusted wrappers |
| `memory/context_checkpoint.py` | Named transcript snapshots |
| `memory/handoff.py` | Handoff markdown + JSON export |
| `memory/compaction_ops.py` | Shared compaction + auto-checkpoint |
| `agent/subagent_profiles.py` | Bundled + `~/.kite/subagents/` persona loader |
| `data/subagents/*.md` | Base personas (scout, reviewer, shell, coder, context) |
| `bench/` | `kite bench` timing suite |
| `application/` | Flattened 0.9 modules: contracts, `execution.py`, `policy.py`, `verification.py`, SQLite store |
| `eval.py` | Recorded `ReplayBundle` (no live providers) |
| `tasks.py` | Headless / `kite tasks` batches |
| `plugins/extensions.py` | `.kite/extensions` `register_tool` loader |
| `skills/` | Load `SKILL.md`; install npm/git or **symlink** a local folder into `~/.kite/skills` |
| `ui/repl.py` | prompt_toolkit REPL, slash expansion, keybindings |
| `ui/commands.py` + `ui/tables.py` | Single slash registry (`BUILTINS` / `ALIASES` / `LEGACY_ALIASES`) + canonical sessions table (`memory/session_format` re-exports) |

---

## Context & memory

Two separate systems:

**Project context (once per run)** — Injected into the system prompt: repo tree, **repo map** (symbols; git-changed first), git status, `AGENTS.md` / `KITE.md`, plus **execution context** (`project_root`, `execution_cwd`, `execution_mode`). Cached briefly; not re-summarized each turn.

Repo maps and directory sketches use bounded `scandir` walks (6,000 entries / 600 source candidates), prune ignored directories, and never follow directory symlinks. Discovery includes the symbol map directly; the former circular import no longer silently disables it. Toolchain detection preserves the project's virtualenv interpreter path rather than dereferencing it to the base Python.

**Transcript compaction (each turn)** — Two window-relative clauses, whichever fires first:

1. **Ratio clause** — `usage.ratio >= scale_compact_ratio(window)`.
2. **Reserve clause** (backstop) — `total_tokens >= window - scale_reserve_tokens(window)`.

Both scale with the model's context window, because the summarization call runs against the transcript it summarizes. A flat ratio would compact a 1M-window model at 750k tokens and then pay to summarize 750k. The defaults:

| Setting | 128k window | 1M window | Notes |
|---|---|---|---|
| `scale_compact_ratio` | 0.75 | 0.65 | −0.05 per doubling past 128k, floor 0.55 |
| `scale_reserve_tokens` | 7,680 | 60,000 | ~6% of window, floor 4,000 |
| `scale_compaction_llm_ratio` | 0.92 | 0.82 | trigger + 0.17, floor 0.70 |

`compaction_ratio`, `compaction_reserve_tokens`, and `compaction_llm_ratio` default to **0 = auto**. A positive value in TOML is an explicit override and wins — scaling applies to the defaults only, never to a user-set number. The three scaling helpers live next to `scale_keep_recent_tokens` in `context/window.py`; note that the reserve grows with the window while the recent-tail budget shrinks with it (capping a tail is safe, capping headroom is not).

Once triggered:

1. **Soft checkpoint** (0.72 of the trigger ratio) — auto-save full transcript to `~/.kite/checkpoints/<session>/` (once per size).
2. Keep the system message and a recent tail (`scale_keep_recent_tokens`: 12% of window, capped by config).
3. Extract **preserved facts** (constraints, errors, paths, tools) from dropped turns.
4. Summarize dropped middle turns (LLM via OpenRouter free tier, or deterministic fallback).
5. Inject a synthetic user message: `Previous conversation summary:` + facts block + summary.
6. Persist a `compact_snapshot` row in the session JSONL so `kite resume` continues from the compacted view.

**Manual:** `/compact` uses the same `run_compaction()` path as the loop. `/checkpoint save|restore` for named snapshots. `/handoff` exports `.kite/handoff-*` for another agent.

Config: `~/.kite/config.toml` — `auto_compact`, `compaction_*` (`0` = auto, see the table above), `[guardrails] execution_mode = restricted|host`.

Session appends leave the JSONL header alone; the `.meta` sidecar is authoritative for update timestamps and runtime identity. Tail resume avoids loading a whole oversized row, recent events are read in reverse, and semantic-memory prompt rendering is lazy. Episodic SQLite lock contention is not corruption: only genuine corruption quarantines the database. Recovery behavior is documented in [the session commands](kite_commands.md#1-cli).

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

Tools implement a common `Tool.run(args) → {ok, output, …}` contract. Production path: **`ToolExecutor.execute(ToolCall)`** → `LocalEnvironment.execute()` → `ToolRegistry` (single authorize → run → normalize pipeline; no parallel tool path).

Single slash registry: `ui/commands.py` (`BUILTINS` / `ALIASES` / `LEGACY_ALIASES`) is the source — `ui/repl.py` fans aliases out to handlers, `ui/complete.py` owns `BUSY_SAFE_SLASHES`, and `ui/approval.py` owns `APPROVAL_KEYS`.

**Mutating tools** (`write`, `edit`, `bash`, …) pass through:

- **PolicyEngine** — path containment, restricted-mode network block (loop entry)
- **Plan mode** — blocked unless `/build` (todo_write still allowed)
- **Approval** — `auto` / `approve` / `trust` / `readonly`; preview diffs for write/edit
- **Guardrails** — bash deny patterns, env-dump block, secret write blocking, output redaction (inside tools)
- **Project trust** — `guardrails/project_trust.py`; trusted cwd skips nested-agent approval (see `~/.kite/trust.json`, `/trust`, `.kite/project.toml`)

**Subagent** — `subagent` tool spawns a bounded nested harness run (max 12 per dispatch, no recursion, no nested `memory`). Prefer bundled `profile=` personas over JIT microscopic workers. Per-worker `model` / `provider` overrides pass through the orchestrator. `task` is a lighter glob+grep fan-out.

**User context** — `USER.md` + `PROFILE.md` + `WORKING.md` under `~/.kite/memory/` only; injected as untrusted soft context on the main agent, skipped for nested subagents.

`grep` streams ripgrep output instead of capturing it all; its Python fallback prunes cache directories and honors context. See [tool behavior](kite_commands.md#4-agent-tools-model-called-not-typed-by-you) and [capture security](SECURITY.md#bounded-output-capture).

Shell/job completion is event-driven. `BackgroundJob.wait(timeout) -> bool` waits for terminal status and output, returning `False` on timeout rather than polling. User-facing job behavior is documented in [the tool reference](kite_commands.md#4-agent-tools-model-called-not-typed-by-you).

---

## Event-driven UI

The agent emits events; the UI never polls internal state. Event sequencing and in-memory sinks are synchronized, and observer failures are isolated from the control loop. High-frequency stream text is coalesced by the UI; the canonical final submission replaces provisional output to prevent duplicate or contradictory answers.

The optional JSONL trace sink attaches to `AgentRuntime`'s existing event fan-out, before UI coalescing, for REPL, one-shot, and task runs. `KITE_TRACE_JSONL` is read once at runtime construction; disabled tracing installs no listener and adds no per-event environment lookup. See [trace usage and record format](kite_commands.md#runtime-event-tracing) and [privacy guarantees](SECURITY.md#runtime-trace-files).

| Event | UI effect |
|-------|-----------|
| `stream_delta` / `stream_reasoning` | Live assistant text |
| `tool_start` / `tool_progress` / `tool_end` | Tool chips, spinner, write/edit diff preview, collapsed output |
| `subagent_start` / `subagent_end` | Crew board rows; `/live agents` streams nested activity |
| `job_output` | Background bash/subagent line streaming (redacted) |
| `context` | Footer token meter |
| `compact` | Compaction notice (`↻ before → after`) |
| `checkpoint` | Context snapshot saved (`◇ checkpoint`) |
| `approval` | Inline approve/deny prompt |
| `orchestrator_start` / `orchestrator_end` | Parallel crew dispatch summary |
| `submit_blocked` | Verification gate rejected completion; reason in stream |
| `verification_status` | Footer updates (`verified`, `changed_unverified`, `failed`, …) |
| `todo` | Live plan checklist |

Streaming uses stderr for loaders; stdout stays clean for copy/paste.

---

## Extension points

| Want to… | Hook |
|----------|------|
| Add a CLI command | `cli/run.py` + handler module |
| Add a slash command | `ui/commands.py` + `ui/repl.py` + `ui/complete.py` |
| Add a tool | `tools/coding.py` or plugin; register in runtime config `[tools].enabled` |
| Register a Python extension | `.kite/extensions/*.py` via `plugins/extensions.py` (`ExtensionAPI.register_tool`) |
| Add a provider | `data/catalog.toml` + credentials env var |
| Add a skill | `SKILL.md` in `~/.kite/skills` or `.kite/skills`; `/skills add pkg` or `/skills add ./path` (symlink) |
| Swap sandbox | Replace `env/local.py` (same `execute(action)` contract) |
| Override summarizer | `AgentRuntime` slot or `compaction_use_llm` in user config |

---

## Testing & CI

- **Local:** `pytest` from repo root; see the [test policy](AGENTS.md#tests--ci) and [suite layout](tests/README.md).
- **CI:** `.github/workflows/tests.yml` — Linux and Windows × Python 3.11/3.12: `sync_version --check`, `ruff check src tests`, `pytest -q`, `kite bench --check`.

Focus areas: guardrails/SSRF, approval, agent loop, sessions, CLI/REPL, credentials/BYOS.

---

## Related docs

| Doc | Use when |
|-----|----------|
| [kite_commands.md](kite_commands.md) | CLI/REPL command reference |
| [CONTEXT.md](CONTEXT.md) | Term definitions |
| [AGENTS.md](AGENTS.md) | Hacking on this repository |
