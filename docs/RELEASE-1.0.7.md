# Kite v1.0.7

**Date:** 2026-10-09

This release bundles the runtime hot-path and correctness work with the
developer-verification and documentation PR stack (#111–#113).

## Runtime performance and correctness

- Runtime hot paths improve model construction, headless startup, streaming,
  reasoning accumulation, path completion, picker performance, and
  large-transcript/session operations.
- Prompt caching no longer reuses stale history after transcript truncation;
  repository symbol maps are populated; narrow-terminal streaming handles
  chunk boundaries, wide characters, and tabs correctly.
- Corrupt or missing session headers remain listable and resumable; transient
  SQLite locks no longer quarantine episodic data. Resume exit codes,
  background-job watchdogs, shell output limits, secret redaction, interpreter
  selection, and invalid task argument handling are corrected.

## Developer verification

- Added offline end-to-end smoke coverage using the real CLI and a loopback
  recorded provider, plus isolated worktrees, faster CI workflows, and CLI
  profiling.
- Added opt-in, redacted JSONL runtime tracing with `KITE_TRACE_JSONL`.
- Added `kite bench --suite full` with 43 measurements and MAD-aware `--save`
  and `--compare` support.
- Reworked the test suite into named, isolated tests and deterministic fixtures;
  external network calls are blocked in test isolation.
- Documented performance and behavior changes, runtime traces, test policy,
  and the development loop.


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
