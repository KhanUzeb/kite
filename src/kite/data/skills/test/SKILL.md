---
name: test
description: Write or run tests for the current change.
---

# Test skill

Use when adding coverage or verifying behavior.

## Steps
1. Detect the test runner (`pytest`, `npm test`, `cargo test`, `go test`, etc.). `cd` or `set_cwd` into the package root if needed.
2. Find existing tests near the code under change; mirror their style.
3. Add or update focused tests for the behavior.
4. Run the smallest relevant subset first, then broaden if green.
5. Fix failures before declaring done.

## Tips
- Prefer deterministic tests (no network/time flakes)
- Name tests after behavior, not implementation details
