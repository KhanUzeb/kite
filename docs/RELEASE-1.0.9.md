# Kite v1.0.9

**Date:** 2026-10-23

## Highlights

A performance and cleanup release. Session tool events no longer rewrite the
metadata sidecar on every append, `KITE_HOME` resolution is cached, and roughly
1,000 lines of unwired modules, unused helpers, and misnamed tests are gone.
CLI and REPL behavior is unchanged.

## Session and config performance

- Durable events (`tool_start`, `tool_end`, approvals, checkpoints, …) now append
  to the transcript only. An event changes neither provider/model/reasoning nor
  the message count carried by the sidecar, so the per-event atomic write +
  fsync bought no durability. Recency continues to use the transcript/sidecar
  mtime ranking key; message appends and `note_runtime` still refresh the
  sidecar.
- `record_event` resolves the persistence policy once per event and reuses it for
  redaction instead of re-reading `config.toml` for each row.
- A `KITE_HOME` override caches its resolved path, avoiding a filesystem
  round-trip on every config and session read.

Illustrative local measurement for the append path (2,500 events, same machine,
not a portable timing guarantee): ~7.3 ms/event before, ~1.1 ms/event after.

## Cleanup

- Removed unwired application-layer modules (`application/context.py`,
  `persistence.py`, `ui.py`, `event_payloads.py`), the token-report/routing/tool-tier
  experiments, and dead UI wrappers. None were reachable from the CLI or REPL.
- Removed unused `HarnessDependencies` slots and miscellaneous dead helpers.
- Renamed test bundles that said "token efficiency" while covering live
  reasoning/cache, registry, read, spill, and error behavior; tests for removed
  modules were deleted.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.9
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.9] entry.
