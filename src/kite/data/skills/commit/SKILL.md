---
name: commit
description: Create a clean git commit following conventional message style.
---

# Commit skill

Use when the user asks to commit changes.

## Steps
1. Run `git status` and `git diff` (and `git diff --staged` if needed).
2. Run `git log -5 --oneline` to mirror the repo's commit style.
3. Stage only relevant files. Never stage secrets (`.env`, credentials).
4. Draft a concise 1–2 sentence commit message focusing on **why**.
5. Commit with a HEREDOC-style message when possible.
6. Run `git status` after to verify success.

## Do not
- Update git config
- Push, force-push, or amend
- Commit unless the user asked
- Use `--no-verify` unless explicitly requested
