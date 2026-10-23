# Kite v1.0.9

**Date:** 2026-10-23

## Highlights

A performance and cleanup release. Session tool events no longer rewrite the
metadata sidecar on every append, slash/plugin/skill machinery loads only when
needed, `KITE_HOME` and config reads avoid redundant filesystem work, and roughly
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
- Windows appends skip `Path.chmod(600)`: Windows only maps that to the read-only
  attribute, while the inherited user-profile ACL already restricts the file.
- A `KITE_HOME` override caches its resolved path, and `UserConfig.load` uses a
  single stat rather than checking `is_file()` and then stat-ing again.

Illustrative local measurement for the append path (same machine, not a portable
timing guarantee): ~7.3 ms/event before this release, ~0.95 ms/event after.

## Startup and system performance

- Plugin, skill, and markdown-command loaders are imported on demand instead of
  at module import. The slash module no longer pulls in Rich/theme setup when a
  plain task is about to run.
- Plain REPL input is rejected before building the full slash index; only input
  that starts with `/` pays for plugin/skill/command discovery.
- Plain `kite run` tasks skip the slash module entirely; only prompts that start
  with `/` import it.
- Illustrative local measurements: cold `import kite.ui.repl` ~655 ms →
  ~590-630 ms; isolated `import kite.cli.slash` ~333 ms → ~110 ms. Direct
  verbatim commands on a quiet machine are the only reliable comparison.

## Cleanup

- Removed unwired application-layer modules (`application/context.py`,
  `persistence.py`, `ui.py`, `event_payloads.py`), the token-report/routing/tool-tier
  experiments, and dead UI wrappers. None were reachable from the CLI or REPL.
- Removed unused `HarnessDependencies` slots and miscellaneous dead helpers.
- Renamed test bundles that said "token efficiency" while covering live
  reasoning/cache, registry, read, spill, and error behavior; tests for removed
  modules were deleted.
- Consolidated duplicate interrupt/persistence assertions and merged the
  question-tool, stream-stall, and diff-render tests into cohesive behavioral
  cases. Collected cases: 465 → 460 (457 passed, 3 platform skips on Windows).

## Compatibility

- LiteLLM 1.106 imports its MCP bridge for every non-empty tools list, even when
  the tools are ordinary function tools. Kite now opts out of that bridge when
  it is available, so the latest LiteLLM no longer triggers the optional `mcp`
  dependency on tool calls.

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
