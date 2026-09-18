---
name: unslop
description: Remove low-quality AI-generated cruft without changing behavior
argument-hint: [file, diff, or focus]
---

Clean up the requested text, file, or current uncommitted changes. Remove low-quality
AI-generated output: unnecessary abstractions, verbose or generic prose, comments that
restate the code, overly defensive code, unused helpers or wrappers, inconsistent
naming, and boilerplate that adds no behavior.

If `$ARGUMENTS` names a file, text, or focus (for example "this README", "these
comments", or "this diff"), scope the cleanup to that. Otherwise clean up the current
uncommitted changes (`git status` / `git diff` first to find the scope).

Rules:

1. Preserve behavior, public APIs, user intent, and factual information.
2. Remove unnecessary complexity instead of adding another abstraction.
3. Delete redundant comments by default; keep comments that explain non-obvious
   constraints (security, concurrency, compatibility, design decisions).
4. Replace generic prose with concise, project-specific language, but do not rewrite
   accurate technical documentation merely to make it shorter.
5. Remove unused code only when it is clearly part of the requested cleanup.
6. Never change runtime behavior, rename public APIs without explicit instruction,
   apply broad unrelated formatting, or touch files outside the requested scope.
7. Never hide warnings or suppress failing tests.

Workflow: inspect first, show a diff before applying changes (use the edit tools so the
normal preview applies), then run the focused verification for the touched area
(tests, typecheck, or lint — whichever fits). End by reporting what was cleaned up
and anything intentionally left alone.

$ARGUMENTS
