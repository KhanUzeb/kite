---
name: init
description: Bootstrap root AGENTS.md (agents.md). Use for /init, kite init --chat, or <bootstrap_check> in context.
---

# Init

Deliverable: **`AGENTS.md` at the repo root** — commands, layout, and conventions an agent needs. Add a short `KITE.md` only for notes that are Kite-specific.

## Fast path
`kite init .` scaffolds it deterministically. Add `--force` to overwrite; that keeps a `.bak.<ts>` backup of the previous file.

## By hand
1. Inspect manifests (`pyproject.toml`, `package.json`, …), CI config, and existing docs for the real install, test, and lint commands. Do not invent commands.
2. Cover: what the repo is, where to change what, how to run tests, and conventions that differ from defaults.
3. Keep it short. Link to existing docs instead of duplicating them.
4. If `AGENTS.md` already exists, show the user what would change and **ask before overwriting**.
5. Do not commit unless the user asked.
