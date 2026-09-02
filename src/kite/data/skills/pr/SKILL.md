---
name: pr
description: Prepare and open a pull request with a clear summary and test plan.
---

# PR skill

Use when the user asks to open, update, or draft a pull request.

## Steps
1. Confirm branch state: `git status`, `git diff`, `git log` vs the base branch (`git diff main...HEAD` or equivalent).
2. Ensure commits are clean (use the **commit** skill if uncommitted work should land first). Do not push unless the user asked.
3. Inspect existing PRs if helpful: `gh_prs` / `gh_pr` (when GitHub tools are enabled) or `gh pr list` / `gh pr view` via bash.
4. Push with `-u` if needed, then create or update the PR:
   - Prefer `gh pr create` / `gh pr edit` via bash with a HEREDOC body.
5. Body format:
   - Summary (1–3 bullets: why)
   - Test plan (checklist)

## Rules
- Never force-push to main/master
- Never invent reviewers, labels, or CI status
- If `gh` is missing or unauthenticated, stop with the draft title/body for the user to paste
- Check CI with `gh_runs` / `gh_run` or `gh run list` when asked about status
