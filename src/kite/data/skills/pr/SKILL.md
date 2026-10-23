---
name: pr
description: Prepare and open a pull request with a clear summary and test plan.
---

# PR skill

Use when the user asks to open, update, or draft a pull request.

## Steps
1. Confirm state: `git status`, `git diff`, and `git log` against the base branch (`git diff main...HEAD` or whatever the repo uses).
2. If uncommitted work belongs in the PR, use the **commit** skill first. Do not push unless the user asked.
3. Check for an existing PR before creating one: `gh pr list` / `gh pr view` (or `gh_prs` / `gh_pr` when GitHub tools are enabled).
4. Push with `-u` only when needed, then `gh pr create` or `gh pr edit` with a HEREDOC body.
5. Body:
   - **Summary** — 1–3 bullets on why this change exists
   - **Test plan** — a checklist of what was actually run and what a reviewer should re-check

## Rules
- Never force-push to main/master, and never force-push any branch unless the user explicitly asked
- Never invent reviewers, labels, linked issues, or CI status
- If `gh` is missing or unauthenticated, stop and hand back the draft title and body for the user to paste
- Check CI with `gh run list` (or `gh_runs` / `gh_run`) only when asked about status
