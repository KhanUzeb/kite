# CONTEXT.md — Kite domain language

Glossary for humans and agents. **Terms and boundaries only** — no file paths, no implementation recipes. For code layout see [AGENTS.md](AGENTS.md) and [docs/kite-system-design.md](docs/kite-system-design.md).

---

## Product

**Kite** — A terminal coding-agent harness. The user describes work; Kite runs a model loop with tools against a **workspace** (a project directory on disk).

**Harness** — Everything outside the raw model API: config, prompts, tools, guardrails, UI, sessions, and the agent loop that ties them together.

**Workspace** — The project directory Kite is acting on. Defaults to the shell’s current directory; can be overridden with `--cwd`. Sandboxed tools cannot escape it.

**Kite home** — Global per-user state (config, API keys, sessions, skills). Not the same as the workspace.

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

**Resume** — Continue a prior **session** with a follow-up message.

**Slash command** — Line starting with `/` in the REPL. **Control slashes** change session state; **prompt slashes** expand into the next user message (skills, markdown commands, plugins).

**Turn** — One user message plus the agent’s response cycle (including tool calls) until the model stops or the user interrupts.

---

## Memory & persistence

**Session** — One chat’s transcript and metadata, stored as JSONL under Kite home. Identified by a session id.

**Trajectory** — Serializable record of a run (messages, tool events) for debug, replay, or `kite apply`.

**Semantic memory** — Durable markdown notes (`MEMORY.md` style) the user asks to remember across sessions.

**Episodic memory** — Short sqlite log of notable events per user/project.

**Compaction** — Summarizing older turns to free context window space while keeping recent messages.

---

## Model & providers

**Provider** — A named backend in the catalog (OpenAI, Groq, NVIDIA NIM, Ollama, OpenRouter, etc.).

**Model** — A provider-specific model id (e.g. `groq/llama-3.3-70b-versatile`).

**Reasoning / effort** — Optional extended-thinking vs low-latency settings when the provider advertises both (`/thinking`, `/fast`, `/reasoning`).

**Credential** — API key (or local endpoint) for a provider, stored in Kite home `.env`, never in the git workspace.

---

## Extensions

**Skill** — A `SKILL.md` pack the model can load when a task matches its description. Invoked via the `skill` tool or prompt slashes like `/commit`.

**Plugin** — A bundle under `.kite/plugins/` that can add slash commands and skills for a workspace.

**Markdown command** — A user-authored prompt file (`.kite/commands/*.md`) invoked as `/name` and expanded into the turn.

**MCP server** — External tool process wired via config; exposes tools as `mcp_<server>_<tool>`.

---

## Agent loop (conceptual)

**Query** — One model call with current messages and tool schemas.

**Action** — A tool invocation the model requested (read, edit, bash, …).

**Observation** — Tool result fed back into the message list.

**Checkpoint** — Optional git commit tagged for agent edits so **undo** can revert the last agent batch.

**Verification** — Evidence the task is done (test output, diff, command result) before treating work as complete.

**Submit** — End of a build turn when the task is finished (bash submit phrase or plain text reply in chat).

---

## UI concepts

**Cell** — One visual block in the stream (user, thinking, answer, tool row, diff, compaction boundary).

**Footer** — Status line: mode, approval, model, effort, context %, cost, branch.

**Collapse** — Tool output truncated by default; user expands with `/expand` or Ctrl+O.

---

## Boundaries (language)

| Term | Is | Is not |
|------|----|--------|
| Workspace | Project being edited | Kite source repo when user runs Kite elsewhere |
| Session | Chat log | Git branch |
| Skill | Reusable prompt/instructions | Python module |
| Provider | Catalog entry + API route | A single model name |
| Harness | Runtime + UI | The LLM itself |
| Trajectory | Run artifact | Live REPL scrollback |

---

## Related docs

- [AGENTS.md](AGENTS.md) — how to work on this repository
- [kite_commands.md](kite_commands.md) — full CLI and slash map
- [docs/cli-ux.md](docs/cli-ux.md) — TUI behavior and shortcuts
- [docs/kite-system-design.md](docs/kite-system-design.md) — architecture atlas
