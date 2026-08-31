---
name: handoff
description: Export session context for another agent or machine
argument-hint: [output directory]
---

Prepare a clean handoff for another coding agent (or a fresh Kite session on another machine).

1. Summarize the current mission, constraints, and decisions in plain language.
2. List files changed, tests run, and failures still open.
3. Tell the user to run `/handoff $ARGUMENTS` (or `/handoff` for the default `.kite/` path) to write:
   - `.kite/handoff-<session>.md` — human-readable brief
   - `.kite/handoff-<session>.json` — machine bundle with checkpoint
4. Include the exact resume command: `kite resume <session-id> "continue from handoff"`.

Do not start new work until the handoff is written if they asked for a handoff.

$ARGUMENTS
