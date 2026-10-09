# Kite v1.0.7

**Date:** 2026-10-09

## Highlights

Runtime hot-path optimizations and correctness fixes reduce startup, streaming,
and test-suite costs while keeping behavior covered by focused, isolated tests.

## Performance and correctness

- Reduced `LitellmModel` construction overhead and headless startup-to-first-query
  latency.
- Improved streamed-answer and reasoning accumulation performance, and reduced
  path-completion and picker costs for large directories and option lists.
- Fixed correctness issues found while optimizing runtime paths; the test suite
  now runs as independent tests rather than relying on shared batching.

## Developer workflow

- Added offline end-to-end smoke coverage, isolated worktrees, a faster CI loop,
  and CLI profiling support.
- Documented performance and behavior changes, runtime traces, test policy, and
  the development loop.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.7
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.7] entry.
