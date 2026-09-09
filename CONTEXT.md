# CONTEXT.md — Kite domain language

Glossary for humans and agents. **Terms and boundaries only** — no file paths, no implementation recipes. For code layout see [AGENTS.md](AGENTS.md) and [docs/kite-system-design.md](docs/kite-system-design.md).

---

## Product

**Kite** — A terminal coding-agent harness. The user describes work; Kite runs a model loop with tools against a **workspace** (a project directory on disk).

**Harness** — Everything outside the raw model API: config, prompts, tools, guardrails, UI, sessions, compaction, checkpoints, and the agent loop that ties them together.

**Workspace** — The project directory Kite is acting on. Defaults to the shell’s current directory; can be overridden with `--cwd`.

**Kite home** — Global per-user state (config, API keys, sessions, skills, checkpoints). Not the same as the workspace.

---

## Execution & sandbox

**Project root** — The discovered repository root (`.git`, `pyproject.toml`, etc.). Used for project instructions, tree, and git context.

**Execution cwd** — The active working directory for file tools and bash. Defaults to the launch cwd; may change via `set_cwd` or bash `cwd`.

**Execution mode** — `host` (packaged default) or `restricted`. Host mode allows paths outside the session cwd (protected paths still blocked). Restricted mode sandboxes file/bash paths to the session. Toggle in the REPL with `/restricted on|off` (alias `/sandbox`). Production tool calls authorize through **`PolicyEngine`** (path containment, network in restricted mode); **`GuardrailPolicy`** still applies bash denylist and output clamp inside tools.

**ToolExecutor** — 0.9 pipeline: `derive_intent` → `PolicyEngine.authorize` → optional approval → `runner` → `ToolResult`. Wired into the production agent loop; legacy direct `env.execute` path remains when disabled.

**Repo map** — Compact symbol sketch (functions/classes per source file) injected into project context. Git-changed files are ranked first (`*` marker).

**RunSpec** — Immutable description of one harness run (task, workspace, limits, model, approval).

**EventEnvelope** — Sequenced, identified lifecycle event (id, run_id, sequence, kind, payload). Replaces ad-hoc `Event(kind, payload)` as the canonical record.

**ApplicationRunService** — Application-layer entry: `run(RunSpec, HarnessDependencies) -> RunResult`. Existing `Harness` is a compatibility adapter.

**Sandbox** — Guardrail policy on paths and bash — not a fake “unrestricted” label. The model is told the real mode.

---

## Modes of work

**Plan mode** — Read-only agent mode. Inspect and checklist; no mutating tools unless the user explicitly switches.

**Build mode** — Default apply mode. Edits, bash, and writes are allowed subject to **approval**.

**Approval** — How much autonomy mutating tools get in a session: `auto`, `approve`, `trust`, or `readonly`.

**Role** — Optional persona (`architect`, `implementer`, `debugger`) that adjusts the system prompt fragment.

---

## Conversation surfaces

**REPL** — Interactive chat (`kite` / `kite chat`). User types turns; slash commands control the session without going to the model.

**One-shot run** — Single task via `kite run` (or `kite exec` for CI-style quiet runs).

**Headless run** — Non-interactive execution with line-oriented stderr logging (`[tool]`, `[crew]`, `[out]`). Triggered by `kite run --headless`, `-q`, non-TTY stdout, or `kite tasks run`. Approval modes that need prompts (`approve`, `readonly`) upgrade to `auto`.

**Task batch** — A JSONL or plain-text file of prompts run sequentially via `kite tasks run`. Each line may be JSON (`task`, `label`, `cwd`, `mode`, …) or a raw prompt. Distinct from REPL `/tasks` (queued follow-ups during a busy turn).

**Resume** — Continue a prior **session** with a follow-up message.

**Slash command** — Line starting with `/` in the REPL. **Control slashes** change session state; **prompt slashes** expand into the next user message (skills, markdown commands, plugins).

**Turn** — One user message plus the agent’s response cycle (including tool calls) until the model stops or the user interrupts.

---

## Memory & persistence

**Session** — One chat’s transcript and metadata, stored as JSONL under Kite home. Identified by a session id. **Session persistence** (`full` | `redacted` | `disabled`) controls whether and how transcripts are written — default `redacted` recursively strips secrets before disk.

**Skill trust** — Bundled skills are trusted; npm, git, project, and user-local skills are untrusted. Provenance (`origin`, `trust`) is visible to the model and in `/skills` listings.

**Recursive redaction** — Sanitizer that walks nested structures (dicts, lists, strings) to remove credential-shaped values from audit logs, events, sessions, and tool output.

**Trajectory** — Serializable record of a run (messages, tool events) for debug, replay, or `kite apply`.

**User identity** — Global markdown at `~/.kite/memory/USER.md` (who you are: name, role, comms prefs). Injected when present; wrapped as **untrusted** user-authored content. Never per-repo.

**Profile** — Global markdown at `~/.kite/memory/PROFILE.md` (stack, goals, constraints). Same injection rules as user identity. Distinct from semantic facts and working rhythm.

**Semantic memory** — Durable markdown notes (`~/.kite/memory/MEMORY.md` user-global; optional `<repo>/.kite/MEMORY.md` project-scoped). **Opt-in for prompts:** injected only when the user loaded memory this session (`/remember`, `/memory`) or config says `[memory] inject = "always"`.

**Episodic memory** — Short sqlite log of notable events per user/project. Same opt-in rule as semantic memory when rendered into the prompt.

**Working rhythm** — Fluid long-term context about how the user tends to work (`~/.kite/memory/WORKING.md` + episodic `style` signals). Injected when present as soft **untrusted** context — not weighted policy, not opt-in like semantic memory. Distinct from concrete `/remember` facts.

**Working-state continuity** — Structured mission/done/next brief written after compact or budget continue. Injected as resume context, **not** durable memory; never auto-pinned to MEMORY.md unless the user asked to remember.

**Compaction** — Summarizing older turns to free context window space while keeping recent messages and **preserved facts** (constraints, errors, paths, bash commands, edited paths from verification). Defaults (override in `data/configs/default.toml`): ~12k chars project context, 12k-token recent tail (scaled down on smaller model windows), 5k-char tool observations. At **55% context**, old tool outputs are soft-trimmed; at **75%**, full compaction runs with merged summary blocks.

**Auto venv** — When `[environment] auto_venv = true` (default), bash subprocesses prepend the project `.venv`/`venv` to `PATH` if `pyvenv.cfg` exists.

**Live terminal** — `/live` toggles streaming bash output in the REPL while tools run (redacted).

**Live subagents** — `/live agents` streams nested crew tool and shell output with worker prefix (`◆ Scout · …`). Redacted like live terminal.

**Subagent profile** — Bundled persona (`scout`, `reviewer`, `shell`, `coder`, `context`) or custom `~/.kite/subagents/*.md`. Passed as `profile=` on the `subagent` tool; composes system prompt + task. Custom profiles are untrusted.

**Subagent crew** — Parallel or background nested harness runs via `subagent` tool. Max 12 workers per dispatch; nested workers cannot recurse (`subagent` stripped) or write global memory (`memory` stripped). Monitor with `/agents`; stop with `/kill`.

**Context checkpoint** — Named snapshot of the full model transcript (and todos) at a point in time. Distinct from git undo. Stored under `~/.kite/checkpoints/<session>/`.

**Handoff** — Export bundle (markdown + JSON + checkpoint) so another agent or machine can resume the task. Written to `<project>/.kite/handoff-<session>.*`.

---

## Model & providers

**Provider** — A named backend in the catalog (OpenAI, Groq, NVIDIA NIM, Ollama, OpenRouter, etc.).

**Model** — A provider-specific model id (e.g. `groq/llama-3.3-70b-versatile`).

**Reasoning / effort** — Optional extended-thinking vs low-latency settings when the provider advertises both (`/thinking`, `/fast`, `/reasoning`).

**Credential** — API key (or local endpoint) for a provider, stored in Kite home `.env`, never in the git workspace.

---

## Extensions

**Skill** — A `SKILL.md` pack the model can load when a task matches its description. Invoked via the `skill` tool or prompt slashes like `/commit`. Global libraries: `~/.kite/skills` and `~/.agents/skills` (symlinks and Windows junctions followed). Project copies may link from `.kite/skills/<name>` or `.agents/skills/<name>`.

**Skill install** — `/skills add` or `kite skills --add`: npm/npx/GitHub copy into the global library, or a local path **linked** there. Reinstall unlinks the pointer; it does not delete the real tree.

**Plugin** — A bundle under `.kite/plugins/` that can add slash commands and skills for a workspace.

**Markdown command** — A user-authored prompt file (`.kite/commands/*.md`) invoked as `/name` and expanded into the turn.

**Custom tool** — A programmatic tool registered via `Harness.extra_tools` or `.kite/extensions/*.py` (`ExtensionAPI.register_tool`). Replaces the removed MCP stdio integration; legacy `[[mcp]]` keys in runtime TOML are ignored.

**Context7 (built-in)** — The only bundled docs integration: `context7_resolve` + `context7_docs` call the Context7 HTTP API (MCP-compatible workflow). Optional `CONTEXT7_API_KEY` in `~/.kite/.env`. No other MCP servers are built in.

**Web tools (built-in)** — Free stdlib research: `websearch` (DuckDuckGo HTML), `webfetch` (extracted page text), `webcrawl` (same-origin crawl). No API keys. Prefer Context7 for library APIs; web tools for news, releases, and arbitrary URLs.

**Execution cwd** — Session working directory for file tools and bash. `set_cwd` can move outside the project root when asked; the sandbox then follows that directory (protected system paths still blocked). Default is **host** mode; use `/restricted on` for a tighter sandbox.

---

## Agent loop (conceptual)

**Query** — One model call with current messages and tool schemas.

**Action** — A tool invocation the model requested (read, edit, bash, …).

**Observation** — Tool result fed back into the message list (structured dict; normalized through `ToolResult`).

**Git checkpoint** — Optional git commit tagged for agent edits so **undo** can revert the last agent batch. Not the same as a **context checkpoint**.

**Verification** — Evidence the task is done (test output, diff, command result) before treating work as complete.

**VerificationPlan** — Artifact-aware required checks derived from touched paths and workspace layout (monorepo package roots, ecosystems). HTML structural parse ≠ pytest.

**WorkspaceProfile** — Discovered packages (Python/JS/Rust/Go markers), default test commands, and optional `.kite/verification.toml` overrides. Verification scopes checks per package, not a single `src/`→`tests/` assumption.

**Tool effect** — Canonical capability tag (`workspace_read`, `network`, `nested_agent`, …) derived per tool call; `PolicyEngine` authorizes effects.

**Evidence ledger** — Journaled `VerificationRecord`s and `EvidenceVerifier` digests linking final claims to tool results; model prose cannot satisfy verification alone.

**ReplayBundle** — Recorded run transcript for eval/replay without live providers. May include `events` and `acceptance` criteria (`content_contains`, `event_kinds`, `min_events`).

**Submit** — End of a build turn when the task is finished. Preferred: structured **`submit`** tool with `message` (Done / Changed / Verification sections). Legacy: bash `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`. In interactive build chat, a **text-only** reply may submit **only when the user's last turn was casual** (hi, thanks, short non-task Q&A) — not when the assistant reply looks like a greeting. Task requests (`lower tests`, `fix bug`, …) require tools, verification, or `submit`; greeting-only replies get an idle nudge.

**Text submit (casual chat)** — Harness rule in `DefaultAgent._allow_text_submit`: interactive build mode ends on prose without tools when `_is_casual_user_turn(last_user_message)` is true. Assistant content like `Hey! 👋` does not trigger submit on its own.

**Interrupt** — User cancellation (Ctrl+C) propagates to the model stream and long-running bash; does not kill the REPL.

---

## UI concepts

**Cell** — One visual block in the stream (user, thinking, answer, tool row, diff, compaction boundary).

**Footer** — Status line: mode, approval, model, effort, running command, tok/s, cache hit, context %, cost, branch.

**Collapse** — Tool output truncated by default; user expands with `/expand` or Ctrl+O.

---

## Boundaries (language)

| Term | Is | Is not |
|------|----|--------|
| Workspace | Project being edited | Kite source repo when user runs Kite elsewhere |
| Session | Chat log | Git branch |
| Context checkpoint | Transcript snapshot | Git commit |
| Git checkpoint | `kite:` commit for `/undo` | Context snapshot |
| Skill | Reusable prompt/instructions | Python module |
| Provider | Catalog entry + API route | A single model name |
| Harness | Runtime + UI | The LLM itself |
| Handoff | Exported brief + checkpoint | Live REPL scrollback |

---

## Related docs

- [AGENTS.md](AGENTS.md) — how to work on this repository
- [kite_commands.md](kite_commands.md) — full CLI and slash map
- [architecture.md](architecture.md) — layers and extension points
- [docs/kite-system-design.md](docs/kite-system-design.md) — architecture atlas
- [docs/RELEASE-0.9.0.md](docs/RELEASE-0.9.0.md) — 0.9 release notes
