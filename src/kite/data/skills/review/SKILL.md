---
name: review
description: Review local changes for correctness, risk, and simplicity.
---

# Review skill

Use when asked to review a diff or PR-like change set.

## Checklist
1. `git status` / `git diff` to see the full change.
2. Correctness: does it do what was intended?
3. Edge cases and error paths.
4. Security: injection, path traversal, secret leakage.
5. Simplicity: any unnecessary abstraction or duplication?
6. Tests: are they present and meaningful?

## Output format
- Summary (2–4 sentences)
- Findings (ordered by severity)
- Open questions / residual risk

If the review spans a long session, suggest `/handoff` so another agent can continue with your findings captured.
