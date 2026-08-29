---
name: debug
description: Systematic debugging of failing tests, stack traces, or unexpected behavior.
---

# Debug skill

Use when something is broken and the cause is unclear.

## Steps
1. Reproduce: capture the exact command and full error output.
2. Localize: identify the failing file/function from the stack trace.
3. Hypothesize: list 1–3 likely causes; pick the cheapest check first.
4. Instrument: read relevant code; add temporary prints only if needed.
5. Fix the root cause with a minimal edit.
6. Re-run the original failing command and one nearby regression check.
7. Remove temporary debug instrumentation.

## Rules
- Do not shotgun-rewrite large files
- Prefer failing tests as the reproduction harness
- Stop and summarize if blocked after a few cycles
