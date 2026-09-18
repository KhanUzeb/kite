---
name: create-agent
description: Scaffold a reusable subagent persona under ~/.kite/subagents (not root AGENTS.md). Use when the user wants a dedicated helper agent, reviewer, or crew member — distinct from project bootstrap (`init` skill).
---

# Create agent

Deliverable: a **subagent profile** markdown file the harness can dispatch via the subagent tool (`profile=<id>`).

This is **not** project bootstrap. For root `AGENTS.md`, use the `init` skill or `kite init`.

## When to use

- User asks to create/add a custom agent, persona, or subagent.
- User wants a specialized worker (reviewer, scout, shell-only, etc.) without changing repo-wide `AGENTS.md`.

## Procedure

1. Pick a short **id** (kebab-case, e.g. `api-reviewer`).
2. Scaffold without overwriting:
   - CLI: `kite subagents init <id> --role auto --description "one line"`
   - REPL: `/agents init <id>`
3. Edit `~/.kite/subagents/<id>.md` — frontmatter + system instructions.
4. Reload if needed: `/agents reload`
5. Dispatch with `profile=<id>` on the subagent tool, or `/agents show <id>` to verify.

## Guardrails

- Do not put subagent-specific prompts into root `AGENTS.md` unless the user wants that file updated.
- Never commit API keys; personas are user-local under `~/.kite/subagents/`.
