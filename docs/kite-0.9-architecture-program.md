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
| A | CI baseline, contracts, EventEnvelope, compatibility adapters | Adapter landed |
| B | ContextSnapshot, ContextAssembler, structured compaction | Adapter landed |
| C | ToolCall/Result, PolicyEngine, ProcessRunner, ChangeJournal | Adapter landed |
| D | SQLite event store, resume, handoff cascade | Adapter landed (JSONL still production) |
| E | ModelGateway, typed retries, BudgetLedger | Adapter landed |
| F | Evidence-based verification | Adapter landed |
| G | CLI/REPL service split, extension context | Adapter landed (CLI/REPL still legacy) |
| H | Recorded replay, evaluation harness, docs | Adapter landed |

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
