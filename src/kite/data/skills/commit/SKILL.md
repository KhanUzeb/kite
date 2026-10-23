---
name: commit
description: Create a clean git commit following conventional message style.
---

# Commit skill

Use only when the user asked to commit. Inspect first; never commit on your own initiative.

## Steps
1. `git status` and `git diff` (plus `git diff --staged` if anything is already staged).
2. `git log -5 --oneline` and match the repo's subject style (conventional commits if that is what history shows).
3. Stage only the files that belong to this change. Never stage secrets (`.env`, credentials, keys) or unrelated edits.
4. Write a 1–2 sentence message about **why**, not a file list.
5. Commit with a HEREDOC so the message is not mangled by shell quoting.
6. `git status` again and confirm the commit landed and the tree is as expected.

## Do not
- Update git config, or touch hooks
- Push, force-push, or `--amend` (including `--amend` to "fix" a hook failure)
- Commit an empty or mixed-in-unrelated diff
- Use `--no-verify` unless the user explicitly asked
