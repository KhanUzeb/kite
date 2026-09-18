---
name: init
description: Bootstrap a coding project for AI agents — generate root AGENTS.md (agents.md standard). Use when the user runs /init, kite init --chat, or asks to bootstrap agent guidance for a repo.
---

# Init

Deliverable: **`AGENTS.md` at the repo root** (https://agents.md). Optional: keep or create a short `KITE.md` for Kite-specific notes.

## When to use

- The project context contains `<bootstrap_check>`.
- The user runs `/init` or `kite init --chat`.
- The user asks to bootstrap, init, or generate AGENTS.md for a project.

If the workspace is not a meaningful git repo or has no real code, **do not bootstrap**. Explain why.

## Fast path (no model guesswork)

When the user only wants files on disk, prefer the deterministic CLI:

```bash
kite init .
kite init . --force   # backup then overwrite
```

## Agent-guided procedure

### 1. Identify workspace shape

Single repo, monorepo, or parent directory with multiple repos. For multiple independent git repos, write a root AGENTS.md that explains relationships and bootstrap each sub-repo separately.

### 2. Inspect the codebase — evidence over guesses

Detect ecosystem from manifests (Python `pyproject.toml`, Node `package.json`, Rust `Cargo.toml`, Go `go.mod`). Read CI config (`.github/workflows/`, etc.) for the canonical test command. Infer default branch with:

`git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || git config init.defaultBranch || echo main`

### 3. Write AGENTS.md

Path: `<repo-root>/AGENTS.md` only (no symlinks).

**If the file does not exist:** write a concise template (setup, layout, testing, PR conventions, security) filled from step 2. Aim for under ~80 lines.

**If the file exists:** ask the user to choose:

1. **Skip** (default if they decline changes)
2. **Overwrite with backup** → `AGENTS.md.bak.<unix-ts>` then write
3. **Show diff** — print unified diff; user applies edits manually

Do not write until they pick when overwriting is involved.

### 4. Tell the user

Report created / skipped / overwritten (with backup path). Remind them to commit AGENTS.md when ready.

## Guardrails

- Base content on what the repo actually needs, not generic filler.
- Do not run `git commit` unless the user asked.
- Do not add Kite-only branding sections to AGENTS.md — keep it portable for every coding agent.
