# Kite — System Design, Code Atlas & Engineering Notes

**Version:** 0.4.0  
**Stack:** Python 3.12 · LiteLLM · Rich · uv  
**Lineage:** mini-swe-agent (loop) × tau / Hugging Face (tools, events, catalog, skills, sessions)  
**Companion UX spec:** [cli-ux.md](cli-ux.md) (PDF: `docs/cli-ux.pdf`)  
**Generated for:** weekend hybrid slim coding-agent harness

---

## 0. One-sentence pitch

Kite is a **slim coding-agent harness**: a mini-swe-agent–style sync loop (query → tools → observe → repeat) wrapped in tau-inspired **runtime assembly** (providers, prompts, skills, guardrails, compaction, JSONL memory).

---

## 1. Goals & non-goals

### Goals
- Hackable in one sitting; every layer readable alone
- Multi-provider models via a **config catalog** (not hardcoded SDKs)
- Real coding tools (`read` / `write` / `edit` / `bash` / `grep` / `glob` / `ls` / `todo_*` / `task` / `webfetch` / `skill`)
- Context engineering: KITE.md + AGENTS.md, git status, tree sketch, token estimate, compaction
- Durable sessions + trajectories for debug / resume
- Guardrails that fail closed on path escape & destructive bash
- CLI-first Rich TUI: streaming, collapsed tools, live plan, diffs, approval, plan/build modes

### Non-goals (deliberately deferred)
- Full-screen Textual TUI (we shipped a single-column Rich REPL instead)
- OAuth login flows, extension marketplace
- Session tree branching / leaf replay (tau has this; we stay linear)
- Benchmark runners (SWE-bench batch) — env swap later is enough
- Persistent shell sessions
- Nested LLM sub-agents (`task` is a bounded glob+grep summary, not a second model loop)

---

## 2. Ancestry: what we stole and what we rejected

### From mini-swe-agent
| Keep | Reject / defer |
|------|----------------|
| `Agent` / `Model` / `Environment` split | Bash-only as the sole tool |
| Linear `messages[]` == trajectory | Regex text-action parsing as default |
| `step = query → execute_actions` | YAML Jinja mega-templates as only config |
| Exception control flow (`Submitted`, `LimitsExceeded`) | Growing benchmark/docker matrix in v1 |
| Stateless `subprocess` per bash | — |
| Cost / step / wall-time limits | — |

### From tau (huggingface/tau)
| Keep (slimmed) | Reject / defer |
|----------------|----------------|
| Layer boundary: brain ≠ UI | Three-package monorepo (`tau_ai` / `tau_agent` / `tau_coding`) |
| Typed tools + schemas | Async provider stream → rich event taxonomy |
| Config-driven provider catalog | Full OAuth / catalog.toml megacatalog |
| Project context discovery | Session tree + compaction entry types |
| Skills as `SKILL.md` | Extension runtime / local llama.cpp backends |
| Context accounting + compaction | Full-screen Textual app (Rich linear TUI instead) |
| Events as observer contract | Pi-compatible message wire types everywhere |
| Slash commands + session memory | Session tree / leaf replay |

### Hybrid thesis
> **mini’s loop is the engine; tau’s assembly is the cockpit.**  
> Don’t port tau’s product surface. Port the *boundaries*.

---

## 3. System design (visual)

### 3.1 Package map

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLI (cli/run.py) + ui/                        │
│  kite | chat | run | resume | …                                  │
│  plan/build · approval · slash commands · status footer          │
└────────────────────────────┬────────────────────────────────────┘
                             │  Event listener (RunDisplay)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Harness → AgentRuntime                        │
│  load config · resolve model · assemble prompt · load skills     │
│  mode filter tools · guardrails · session · approver/checkpoints │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DefaultAgent (loop)                         │
│   while not exit:                                                │
│     LoopCompactor.maybe_compact()                                │
│     query(Model) → [approval] execute_actions → observations     │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────────┐
│ LitellmModel              │   │ LocalEnvironment + ToolRegistry │
│ streaming + should_stop   │   │ read write edit bash grep glob  │
│ tool_calls → actions[]    │   │ ls todo task webfetch skill     │
└───────────────────────────┘   └─────────────────────────────────┘
```

### 3.2 Control-flow (mini lineage)

```
run(task)
  ├─ system + instance messages
  └─ loop:
       ├─ compact? ──► replace older turns with summary user msg
       ├─ query()
       │    ├─ limits check → LimitsExceeded / TimeExceeded
       │    └─ model.query(messages) → assistant (+ tool_calls)
       ├─ execute_actions()
       │    ├─ plan mode blocks write/edit/bash (except submit)
       │    ├─ approver(once|session|always|deny|stop) on mutating tools
       │    ├─ env.execute → tool result (+ unified diff on write/edit)
       │    ├─ git checkpoint grouped by in-progress todo/task
       │    └─ format_observation_messages (role=tool)
       ├─ FormatError → repair user msg (or exit after N)
       ├─ Interrupted (Ctrl+C) → exit turn, session stays
       └─ Submitted / exit role → break
  save trajectory.json + session.jsonl
```

### 3.3 Runtime assembly (tau lineage)

```
UserConfig (~/.kite/config.toml)
     +
AgentRuntimeConfig (data/configs/default.toml ⊕ ~/.kite/configs/)
     +
Provider catalog (data/catalog.toml ⊕ ~/.kite/catalog.toml)
     │
     ▼
ResolvedModel { litellm_model, api_base, api_key, context_window }
     │
     ▼
assemble_system_prompt(
    system.md
  + mode_plan.md | mode_build.md
  + project context (KITE.md, AGENTS.md, git, tree)
  + <available_skills>…
)
     │
     ▼
make_coding_tools(..., guardrails, skills) → ToolRegistry
     │
     ▼
DefaultAgent.run
```

### 3.4 Data at rest

```
~/.kite/
  config.toml          # user prefs (default provider/model, compact flags)
  catalog.toml         # optional provider overlay
  configs/*.toml       # optional runtime config overlays
  commands/*.md        # user slash prompts (`/name`)
  skills/*/SKILL.md    # user skills (`/name` or skill tool)
  plugins/<id>/        # plugin.toml + commands/ + skills/
  memory/notes.jsonl   # durable user notes (`/remember`)
  memory/MEMORY.md     # optional pinned user memory
  sessions/*.jsonl     # append-style session transcript
  trajectories/*.json  # full run dumps
  approvals.json       # always-allow tool patterns
  .env                 # optional keys

<project>/.kite/
  commands/*.md
  skills/*/SKILL.md
  plugins/<id>/
  memory/notes.jsonl
  MEMORY.md
```

### 3.5 Message & event model

**Messages** (OpenAI-shaped dicts + `extra`):

| role | meaning |
|------|---------|
| `system` | Assembled system prompt |
| `user` | Task, observations (fallback), compaction summaries, nudges |
| `assistant` | Model text + optional `tool_calls` |
| `tool` | Tool result bound by `tool_call_id` |
| `exit` | Terminal; `extra.exit_status` / `submission` |

**Events** (observer-only; core never renders):

`agent_start` · `turn_start` · `message` · `stream_start` · `stream_delta` · `stream_tool` · `stream_end` · `tool_start` · `tool_end` · `approval` · `todo` · `diff` · `context` · `compact` · `interrupt` · `mode` · `cost` · `turn_end` · `agent_end` · `error`

---

## 4. Module atlas (every package)

### 4.1 `agent/runtime.py` — AgentRuntime
**Job:** One façade that wires the world before the loop.  
**Owns:** options, listeners, last_session, last_resolved, runtime_config, approver, checkpoints, todos.  
**Does:** `prepare()` → resolve model, load skills, gather context, assemble system prompt (+ mode + memory); `run()` → expand slash commands/skills, filter tools by plan/build, build guardrails+tools, session, DefaultAgent.  
**Does not:** render UI, know Rich, parse CLI argv.

### 4.2 `agent/harness.py` — Harness
**Job:** Thin CLI adapter mapping `HarnessConfig` → `RuntimeOptions`. Forwards approver, git checkpoints, and the shared `TodoStore` so a REPL can reuse them across turns.  
**Why it exists:** Keep `cli/run.py` ignorant of runtime internals; allow library use.

### 4.3 `agent/loop.py` — DefaultAgent
**Job:** The mini loop, plus plan/build gating, approval callback, interrupt, git checkpoints.  
**Key methods:** `run`, `step`, `query`, `execute_actions`, `_run_gated`, `request_interrupt`, `add_messages`, `_maybe_compact`, `serialize`/`save`.  
**Interactive / plan:** a text-only assistant reply (no tool calls) ends the turn via `Submitted`. Ctrl+C / `should_stop` raises `Interrupted` without killing the process.  
**Nit:** System prompt already includes project context when built by runtime; `project_context` field remains for standalone agent use.

### 4.4 `agent/compaction.py` — LoopCompactor
**Job:** Before each query, estimate tokens; if `total >= window - reserve`, replace older body with a deterministic summary user message; keep recent tail by token budget.  
**Pick:** Deterministic summary first (no extra LLM spend). LLM summarization can plug in later like tau’s compaction prompts.

### 4.5 `config/runtime.py` — AgentRuntimeConfig
**Job:** TOML schema for agent limits, tools enable-list, guardrails, skills, context.  
**Merge order:** packaged `default.toml` → `~/.kite/configs/default.toml` → `--config` path/name.

### 4.6 `prompts/` — assemble_system_prompt / assemble_instance_prompt
**Job:** Load `data/prompts/*.md` (system, instance, `mode_plan`, `mode_build`), append project context + skill index.  
**Pick:** Prompt text lives in markdown files (editable without Python PRs). Mode extra-section is injected by runtime.

### 4.7 `providers/` — catalog + resolve
**Job:** tau-style catalog; map `(provider, model)` → LiteLLM id + api_base + key env + context window.  
**Providers shipped:** openai, anthropic, openrouter, huggingface, ollama, gemini, groq, opencode-zen, opencode-go, nvidia (NIM), openai-compatible.

### 4.8 `models/litellm_model.py`
**Job:** `completion()` with tools; parse `tool_calls` into `extra.actions`; format tool-role observations; track cost/usage; stream deltas; honor `should_stop` for interrupt.  
**Nit:** Strips kite-only fields (`extra`, `exit`) before API call.

### 4.9 `tools/` — Tool + ToolRegistry + coding tools
**Tools:**
- `read` — numbered lines, offset/limit; huge files auto-truncate
- `write` — create/overwrite; returns a unified diff
- `edit` — exact string replace (unique or replace_all); returns a unified diff
- `bash` — fresh subprocess; submit magic string; highest-privilege, gated
- `grep` — ripgrep (`rg`) when installed, Python walk otherwise
- `glob` — path patterns
- `ls` — directory listing
- `todo_write` / `todo_read` — live plan checklist (auditable tool, not client-only UI state)
- `task` — bounded glob+grep investigation, returns a summary
- `webfetch` — http(s) fetch, size-capped
- `skill` — inject full SKILL.md
- `memory` — list / remember / forget durable notes (`~/.kite/memory` or `.kite/memory`)

Optional `reason` on mutating tools is shown in the UI. Every call goes through `GuardrailPolicy` when enabled. `tools_for_mode` drops write/edit/bash from the schema in plan mode.

### 4.10 `env/local.py` — LocalEnvironment
**Job:** `execute(action)` dispatcher; bash-compat `{"command"}` → bash tool; raises `Submitted` on magic output.

### 4.11 `guardrails/` — GuardrailPolicy
**Checks:** path sandbox to cwd; deny-list bash regexes; block sensitive filenames / secret-shaped writes; redact secret-like strings in outputs; truncate huge outputs.

### 4.12 `skills/` — loader
**Spec:** directory with `SKILL.md` (+ optional YAML frontmatter).  
**Discovery order (later wins):** bundled → `~/.kite/skills` → plugins → `.kite/skills` → `.agents/skills` → config extra dirs.  
**Invocation:** tool `skill`, prompt `/skill:name …` / `/skill name …`, or `/name` when no markdown command took that name.

### 4.12b `commands/` + `plugins/` + `cli/slash.py`
Markdown slash prompts (`--- name / description ---` + `$ARGUMENTS`) live in `data/commands`, `~/.kite/commands`, `.kite/commands`, and `plugins/*/commands`.  
A plugin is a folder with `plugin.toml` (or `plugin.json`) plus optional `commands/` and `skills/`.  
`CommandIndex` overlay: bundled → user commands → plugins → project commands → skills fill unused names. Builtins always win. `/commands new` and `/plugins init` scaffold project files.

### 4.13 `context/` — discovery + window
**Discovery:** project root markers, ancestor `KITE.md` + `AGENTS.md`, git status --short --branch, tree sketch (skip venv/node_modules).  
**Window:** ~4 chars/token estimate; `should_compact`; `compact_messages`.

### 4.14 `memory/`
**Sessions:** JSONL transcript (`session.py`); first line `type=meta`, then `type=message`.  
**Notes:** `store.py` JSONL + optional `MEMORY.md`. `/remember` / `/forget` / `memory` tool. Injected into the system prompt each run. Distinct from `KITE.md` (repo instructions).

### 4.15 `config/` — UserConfig + runtime TOML
**Job:** `~/.kite/config.toml` prefs (default provider/model, api_bases, auto_compact, …). Distinct from **runtime** agent config.

### 4.16 `agent/exceptions.py`
`InterruptAgentFlow` · `Submitted` · `LimitsExceeded` · `FormatError` · `TimeExceeded` · `Interrupted` — all carry messages to append. `Interrupted` ends the turn but keeps the session (REPL can steer).

### 4.17 `agent/events.py` / `agent/protocols.py`
Duck-typed contracts + thin Event dataclass for CLI printers.

### 4.18 `cli/run.py` — CLI
Subcommands: `chat` (default when invoked as bare `kite`), `run`, `resume`, `sessions`, `providers`, `models`, `config`, `context`, `skills`, `commands`, `plugins`, `memory`, `runtime-config`.  
Flags: `--mode plan|build`, `--approval auto|approve|readonly`. Full map: [kite_commands.md](../kite_commands.md).

### 4.19 `agent/mode.py` — plan vs build
**Plan:** read-only tools + `todo_write`; approval defaults to `readonly`; text-only reply finishes with a plan.  
**Build:** full tool set; chat defaults to `approve`, one-shot `kite run` defaults to `auto`.  
Mutating tools: `write`, `edit`, `bash`. Cheap tools are unrestricted.

### 4.20 `ui/` — Rich terminal front-end
**Job:** All rendering. Core still never imports Rich.  
**Modules:** `style` (palette/symbols), `state`, `render` (stream → collapse → diff → footer), `approval` (once/session/always), `git` (checkpoint + `/undo`), `commands` (slash parser), `repl` (cold-start chat), `spinner`, `diff`.  
**Spec:** [cli-ux.md](cli-ux.md).

---

## 5. End-to-end sequence (happy path)

1. User: `kite` (REPL) or `kite run -p anthropic -m claude-sonnet-4-5 "add tests for config" -v`
2. REPL prints chrome + prompt in <500ms; context loads on the first task
3. dotenv + `~/.kite/.env` loaded
4. Runtime loads TOML configs + resolves Anthropic → `anthropic/claude-sonnet-4-5`
5. Credentials check (`ANTHROPIC_API_KEY`)
6. Skills loaded; system prompt assembled with mode section + repo context (KITE.md/AGENTS.md) + skill index
7. Tools built with guardrails; plan mode drops write/edit/bash from the schema
8. Session JSONL created under `~/.kite/sessions/`
9. Agent adds system + user instance messages
10. Loop: compact measure → streamed LLM tool calls → approval (if gated) → tool exec → diffs/todos rendered → tool messages
11. Successful write/edit → staged under the current todo; **one `kite:` commit per todo/task** (not per file). `/undo` reverts the last of those.
12. Model eventually `bash` with `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` (or a text-only reply in chat/plan)
13. Environment raises `Submitted` → exit message → trajectory saved
14. CLI prints result panel + status footer (model, mode, approval, ctx %, cost, branch)

---

## 6. Tradeoffs (honest)

| Decision | Upside | Downside |
|----------|--------|----------|
| Sync loop, not async streams | Simple stack traces; easy to debug | Spinner covers >1s gaps; still not a full-screen TUI |
| LiteLLM as universal adapter | One code path for many providers | Abstraction leaks; weird provider quirks |
| Tool-calling first | Reliable structure vs regex bash | Weaker models / some local LLMs struggle |
| Subprocess-per-bash | Trivial sandbox swap; no stuck shell state | Agents must re-`cd` / re-export every time |
| Deterministic compaction | Free, predictable | Lossy; may drop nuance vs LLM summary |
| Linear sessions only | Tiny code | No branch/undo tree like tau; `/undo` is git-only |
| Guardrails in-process | Fast, always on | Not a security boundary vs malicious local user |
| Catalog TOML slim | Editable without PRs | Drift from real model lists; manual upkeep |
| Magic submit string | Clear batch/eval semantics | Chat/plan also allow text-only turn end |
| Events optional | Core stays pure | Easy to forget to emit new kinds |
| Rich linear TUI (not Textual) | Fast start, works in any tty, streams tokens | Collapse/expand is `/expand` or `-v`, not click |
| Git checkpoint per todo/task | Real undo without a commit-per-file history | Still pollutes history if the user did not want agent commits |

---

## 7. Nits & picks (engineering taste)

### Picks (do more of this)
1. **Boundary over features** — Runtime assembles; Agent loops; CLI prints.
2. **Data-driven providers/prompts/skills** — Prefer TOML/MD over Python constants.
3. **Fail closed on sandbox** — Path escape is an error, not a warning.
4. **Trajectory == messages** — Debugging is “open the JSON”.
5. **uv for envs** — Reproducible, fast; pin `.python-version`.
6. **Skill index in system + full body on demand** — Cheap index, expensive body only when needed (tau lesson).
7. **Guardrail clamp on outputs** — Secrets shouldn’t echo back into the next prompt.

### Nits (fix or watch)
1. Session rewrite-on-append is O(n) per message — fine for weekend scale; later append-only + compaction entries.
2. `litellm_model_id` edge cases for odd openrouter names — add tests.
3. Tree snippet can be large on monorepos — already capped; consider ripgrep-based file list.
4. No retry taxonomy beyond LiteLLM `num_retries` — tau’s provider retry events are richer.
5. `Harress`/`Runtime` duplication of options fields — could collapse to one dataclass.
6. Grep uses ripgrep when `rg` is on PATH; Python walk is the fallback for small repos.
7. Frontmatter parser is line-split YAML-ish — not full YAML; keep skills’ frontmatter simple.
8. Cost accounting depends on LiteLLM hidden params — may be 0 for some providers.
9. Windows shell + `shell=True` — document PowerShell vs cmd differences.
10. Packaged skill path via `importlib.resources` can look ugly in prompts — still readable to the model.
11. REPL builds a new harness per turn so `/plan`/`/build` can swap the tool schema — extra prepare() cost after the first message.
12. Approval “always” patterns live in `~/.kite/approvals.json` — treat that file as a credential-adjacent allowlist.

### Footguns
- Forgetting API keys → runtime raises before loop (good).
- `--no-guardrails` disables sandbox — never use in untrusted task text automation.
- Compaction can remove tool_call/tool_result pairs mid-history — we compact whole older region; keep_recent should stay large enough to avoid orphan tool ids (monitor FormatErrors).

---

## 8. Learning journal (why this shape)

1. **SWE-agent → mini** taught that as models improve, scaffold weight should fall. Bash-only + linear history is a strong baseline for evals.
2. **tau** taught that *product* agents need assembly: catalogs, skills, sessions, context files, events. The mistake is copying the product wholesale into a weekend harness.
3. **Hybrid rule:** steal *interfaces* (Environment.execute, Event listener, SKILL.md, catalog.toml), not *implementation volume*.
4. **Context engineering > prompt poetry:** AGENTS.md + git status + tree + compaction moves needle more than a longer system prompt.
5. **Memory is two layers:** (a) active context window for the model, (b) durable JSONL for humans/resume. Don’t conflate them — compaction changes (a) while (b) can rewrite or later keep full history.
6. **Guardrails aren’t security theater if scoped honestly:** they protect against model mistakes (rm -rf, path escape), not against a hostile operator on the same machine.
7. **Skills beat mega-prompts:** index in system; load full playbook when relevant — same idea as progressive disclosure.

---

## 9. Code details by concern

### 9.1 Submit protocol
Bash output whose first non-empty line is `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` and returncode 0 → `Submitted` with remainder as submission body.

### 9.2 Format errors
Empty assistant with no tool_calls, or invalid tool JSON → `FormatError` user message; after N consecutive → exit `RepeatedFormatError`.

### 9.3 Compaction threshold
`should_compact` iff `total_tokens >= context_window - reserve` (default reserve 16_384). Keep recent ~20_000 tokens of tail.

### 9.4 Provider resolution precedence
CLI `--provider/--model` → user `provider_defaults` / `default_model` → catalog `default_model`.  
`api_bases` in user config override catalog `base_url`.

### 9.5 Tool gating
```
check_tool_call → (block | rewrite args) → [UI approval if mutating] → execute → clamp_output (redact + truncate)
```
Plan mode: mutating tools never enter the schema (and are denied if called). Submit-only bash (`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`) is the exception so a plan can finish.

### 9.6 Skill expand
If the task is a prompt-kind slash (`/commit`, `/explain`, `/skill:debug …`, custom `.md` command), expand it to the skill/command body before `agent.run`.

### 9.7 Plan vs build
`AgentMode` + `ApprovalMode` live on `RuntimeOptions`. Chat defaults: build + approve. `kite run` defaults: build + auto. See [cli-ux.md](cli-ux.md).

### 9.8 Git undo
After a successful write/edit, paths are staged under the **current in-progress todo** (or the user task if there is no checklist). Completing a todo or ending the turn flushes **one `kite:` commit** for that step's files. `/undo` runs `git reset --hard HEAD~1` only if HEAD subject starts with `kite:`.

### 9.9 Extra providers (0.4)
| CLI `-p` | Aliases | Base | Key |
|----------|---------|------|-----|
| `opencode-zen` | `zen`, `opencode` | `https://opencode.ai/zen/v1` | `OPENCODE_API_KEY` (or `OPENCODE_ZEN_API_KEY`) |
| `opencode-go` | `go` | `https://opencode.ai/zen/go/v1` | `OPENCODE_API_KEY` (or `OPENCODE_GO_API_KEY`) |
| `nvidia` | `nim`, `nvidia-nim` | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` (or `NVIDIA_NIM_API_KEY`) |

Zen/Go are OpenAI-compatible gateways (`openai/` + `api_base`). NIM uses LiteLLM's `nvidia_nim/` route. Self-hosted NIM: `kite config --set-provider nvidia --set-api-base http://localhost:8000/v1`. Live ids: `kite models -p zen --select`.

---

## 10. CLI cheat sheet

See [kite_commands.md](../kite_commands.md) for the full map (CLI, REPL slashes, skills, plugins, tools).

```
kite                         # interactive REPL (plan/build)
kite chat --mode plan
kite chat --approval approve
kite config --set-provider openai --set-model gpt-4.1-mini
kite providers
kite models -p anthropic
kite models -p zen --select
kite models -p nvidia --select
kite skills
kite skills --show debug
kite runtime-config
kite context
kite run "explain this repo" -v
kite run --mode plan "how should we add auth?"
kite run --mode build --approval approve "add tests"
kite commands
kite plugins
kite memory
kite memory --remember "prefer ruff"
kite run "/commit"
kite run "/skill:commit" -v
kite resume <session-id> "also write tests"
kite sessions --show <id>
```

REPL slash commands: builtins (`/plan` `/build` `/undo` `/memory` `/remember` `/commands` `/plugins` `/skills` …) plus `/commit`-style skills and markdown commands. Ctrl+C stops the current turn.

---

## 11. Roadmap (sorted by leverage)

1. DockerEnvironment (`docker exec`) — unlocks eval sandboxes  
2. LLM-backed compaction (tau prompts) when deterministic summary loses too much  
3. Append-only session log + compaction entries (stop full rewrite)  
4. ~~Streaming + Textual TUI consuming events~~ **done (0.4):** Rich linear TUI — see [cli-ux.md](cli-ux.md)  
5. ~~ripgrep-backed grep tool~~ **done (0.4)**  
6. Tests for catalog resolve, guardrails, compaction invariants, approval policy  
7. Optional text-action fallback for nested LLM `task` sub-agents  
8. Click-to-expand tool blocks (needs a full-screen TUI if we ever want it)  

---

## 12. File tree (source of truth)

```
kite/
  pyproject.toml
  requirements.txt
  README.md
  .python-version
  src/kite/
    __init__.py
    __main__.py
    agent/              # loop, runtime, harness, mode, events, exceptions
    cli/                # argparse + slash index
    config/             # ~/.kite prefs + runtime TOML
    ui/                 # Rich TUI
    prompts/
    providers/
    models/litellm_model.py
    tools/
    env/local.py
    guardrails/
    commands/           # markdown slash prompts
    plugins/
    skills/
    context/
    memory/
    data/
      catalog.toml
      configs/default.toml
      prompts/{system,instance,mode_plan,mode_build}.md
      commands/{explain,fix,pr}.md
      skills/{commit,debug,test,review}/SKILL.md
docs/
  kite-system-design.md
  cli-ux.md
kite_commands.md
```

---

## 13. Closing design rule

> If a change requires the agent loop to import Rich, Textual, or filesystem layout policy, **put it in Runtime/CLI/`ui/` instead**.  
> If a change requires the catalog to know about tool schemas, **you’ve crossed a layer — stop**.

That single rule is how Kite stays a hybrid *slim* harness instead of a second tau.

---

*End of design document.*
