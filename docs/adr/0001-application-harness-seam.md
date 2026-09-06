# ADR 0001: Application harness seam

**Date:** 2026-09-04  
**Status:** accepted

## Context

Kite 0.8 ran everything through `Harness.run()` with ad-hoc events and direct tool execution. We needed testable contracts for policy, persistence, replay, and CLI exit codes without rewriting the REPL in one release.

## Decision

Introduce `ApplicationRunService` with `RunSpec`, `EventEnvelope`, and `RunResult` as the canonical application-layer entry. Keep `Harness` as a compatibility adapter that wraps `AgentRuntime` and projects legacy dict results until 1.0.

Production chat continues through `Harness` → `AgentRuntime` → `DefaultAgent`. New seams (`PolicyEngine`, `ToolExecutor`, `EvidenceVerifier`, `ReplayBundle`) are wired into the agent loop where cutover is complete.

## Consequences

- Tests can target application contracts without Rich or LiteLLM.
- Dual paths exist temporarily (legacy events + envelopes).
- 1.0 can flip CLI/REPL to `ApplicationRunService.run()` without changing tool behavior.

## Related

- [kite-0.9-architecture-program.md](../kite-0.9-architecture-program.md)
- [RELEASE-0.9.0.md](../RELEASE-0.9.0.md)
