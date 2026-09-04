# Kite 0.9 Architecture Program

This document summarizes the 0.9 target architecture. Implementation proceeds
in milestones A–H; only behavior covered by tests should be treated as shipped.

## Layering

```text
CLI / REPL / Cloud adapters
        ↓
Application run services (RunSpec, ApplicationRunService, RunResult)
        ↓
Harness orchestration (compatibility adapter → AgentRuntime → DefaultAgent)
        ↓
Context, model, tools, policy, persistence, verification adapters
```

## Milestones

| Milestone | Focus | Status |
|-----------|--------|--------|
| A | CI baseline, contracts, EventEnvelope, compatibility adapters | Landed |
| B | ContextSnapshot, ContextAssembler, structured compaction | Landed (adapter) |
| C | ToolCall/Result, PolicyEngine, ProcessRunner, ChangeJournal | **ToolExecutor wired in production loop** |
| D | SQLite event store, resume, handoff cascade | Adapter (JSONL still production) |
| E | ModelGateway, typed retries, BudgetLedger | Adapter landed |
| F | Evidence-based verification | **Collector + EvidenceVerifier in loop** |
| G | CLI/REPL service split, extension context | ApplicationRunService entry; REPL still legacy events |
| H | Recorded replay, evaluation harness, docs | **ReplayBundle + acceptance criteria** |

## Canonical seams

```text
ApplicationRunService.run(RunSpec, HarnessDependencies) -> RunResult
ContextAssembler.build(RunSpec, sources) -> ContextSnapshot
PolicyEngine.authorize(ToolIntent) -> PolicyDecision
ToolExecutor.execute(ToolCall, RunContext) -> ToolResult
ModelGateway.complete/stream(...) -> ModelResponse/ModelStream
EventStore.append(EventEnvelope) and load_run(run_id)
BudgetLedger.reserve/record(...)
ChangeJournal.record/restore(...)
Verifier.consume(ToolResult) -> EvidenceRecord
```

## Compatibility (0.8 → 0.9)

| 0.8 | 0.9 adapter |
|-----|-------------|
| `HarnessConfig` | `RunSpec` via `run_spec_from_harness_config` |
| `Event` | `EventEnvelope` via `LegacyEventBridge` |
| JSONL sessions | Import/export; SQLite adapter landed (JSONL still production) |
| `Harness.run(task)` | `ApplicationRunService.run(RunSpec)` |

See [ADR 0001](adr/0001-application-harness-seam.md).

## CI matrix

Linux and Windows × Python 3.11 and 3.12 (see `.github/workflows/tests.yml`).
