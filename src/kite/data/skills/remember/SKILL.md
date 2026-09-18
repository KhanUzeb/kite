---
name: remember
description: Persist a durable fact in the correct memory layer. Use when the user says remember, save this, don't forget, or /remember.
---

# Remember

Pick **one** layer — narrowest scope first (see system **Memory layers**):

| Layer | When | How |
| --- | --- | --- |
| Project | True only in this repo | Edit `AGENTS.md` / `KITE.md` or `/remember project …` — not global user files |
| User | Follows the human across repos | `/user add`, `/profile add`, `/remember user …`, or memory tool user scope |
| Session notes | Recall later in this project | `/remember …`, semantic `MEMORY.md`, or memory tool |

## Steps

1. Classify the fact (project vs user vs session).
2. Confirm with the user if the layer is ambiguous.
3. Write via the matching slash or memory tool — never store secrets or credentials.
4. Summarize what was stored and where (path or scope).

## Do not

- Store API keys, tokens, or private keys in any memory file.
- Put repo-specific conventions in `USER.md`.
- Treat working continuity / compact summaries as durable memory.
