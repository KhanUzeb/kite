---
name: review
description: Review local changes for correctness, risk, and simplicity.
---

# Review skill

Use when asked to review a diff, a branch, or a PR-like change set. Read the diff before commenting; do not review from filenames.

## Checklist
1. `git status` and `git diff` (or `git diff <base>...<head>`) so you see the whole change, including untracked files.
2. **Correctness** — does it do what was asked, and do the tests actually exercise that?
3. **Edge cases** — error paths, empty inputs, and what happens when a dependency is missing.
4. **Security** — injection, path traversal, secret leakage, and weakened checks.
5. **Simplicity** — unnecessary abstraction, duplication, or drive-by changes unrelated to the task.
6. **Tests** — present and meaningful, not just wired up. Note what was not run.

## Output
- **Summary** — 2–4 sentences on what changed and whether it holds together
- **Findings** — ordered by severity, each with `path:line` and why it matters. Say "no findings" rather than padding
- **Open questions / residual risk** — what you could not verify

Review only. Do not edit the code unless the user asked for fixes. If the review spans a long session, suggest `/handoff` so the findings carry over.
