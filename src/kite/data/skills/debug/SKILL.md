---
name: debug
description: Systematic debugging of failing tests, stack traces, or unexpected behavior.
---

# Debug skill

Use when something is broken and the cause is unclear. One hypothesis at a time; prove it before editing.

## Steps
1. **Reproduce.** Capture the exact command and the full error. Use `set_cwd` when the failure is in a subdirectory or a single package of a monorepo.
2. **Localize.** Read the stack trace top-down and open only the frames in this repo. Note the file, function, and input that fails.
3. **Hypothesize.** Write 1–3 likely causes. Check the cheapest one first (a read or a single assertion) before any edit.
4. **Instrument sparingly.** Read the code. Add a temporary print or log only when reading cannot distinguish the causes, and mark it so it is removed.
5. **Fix the root cause** with the smallest edit that makes the reproduction pass. Do not refactor alongside the fix.
6. **Verify.** Re-run the original failing command, then one nearby regression check (the file's tests, not the whole suite unless it is cheap).
7. **Clean up.** Remove every temporary print, log, and commented-out line.

## Rules
- Do not shotgun-rewrite large files or change several suspects in one edit.
- Prefer an existing failing test as the reproduction harness; add one only if none exists.
- After a few cycles with no new evidence, stop and summarize: what you tried, what you ruled out, and the next check.
