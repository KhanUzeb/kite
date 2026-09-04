# ADR 0001: Application / Harness Seam

## Status

Accepted (Milestone A, Kite 0.9)

## Context

Kite 0.8 couples CLI, REPL, agent loop, LiteLLM, subprocess execution, session
persistence, and Rich UI through `Harness`, `AgentRuntime`, and `DefaultAgent`.
This makes it hard to:

- test orchestration without UI or live providers;
- enforce one canonical run state and event lifecycle;
- swap persistence, policy, or model adapters independently;
- resume or replay runs deterministically.

## Decision

Introduce an **application layer** (`kite.application`) with stable contracts:

| Contract | Role |
|----------|------|
| `RunSpec` | Immutable description of one run |
| `HarnessDependencies` | Injectable adapters (model, tools, policy, persistence, …) |
| `ApplicationRunService` | `run(RunSpec, HarnessDependencies) -> RunResult` |
| `EventEnvelope` | Sequenced, identified canonical events |
| `RunState` | Explicit state machine for run lifecycle |

The existing `Harness` / `HarnessConfig` remain **compatibility adapters**. Production CLI/REPL enter through `ApplicationRunService`; the agent loop routes tools via **`ToolExecutor`** + **`PolicyEngine`** (2026 harness program).

```
CLI / REPL / Cloud
        ↓
ApplicationRunService  ← RunSpec, HarnessDependencies, RunResult
        ↓
Harness (adapter) → AgentRuntime → DefaultAgent
        ↓
Context, model, tools, policy, persistence adapters
```

Legacy `Event(kind, payload)` is bridged to `EventEnvelope` via
`LegacyEventBridge`; UI listeners continue to receive legacy events during
migration.

## Consequences

**Positive**

- Fakes can run a full turn without Rich, LiteLLM, or filesystem side effects.
- Event sequencing and run IDs become first-class for persistence (Milestone D).
- CLI/REPL can become projections of canonical events (Milestone G).

**Negative / migration**

- Temporary duplication: legacy and canonical paths coexist until cutover.
- `HarnessConfig` field changes must update `run_spec_from_harness_config`.
- Call sites should migrate to `ApplicationRunService` incrementally.

## Alternatives considered

1. **Refactor `AgentRuntime` in place** — rejected; too much coupling to unwind
   without a stable external contract.
2. **Big-bang rewrite** — rejected; plan requires adapter-based incremental
   migration with green tests at each milestone.

## References

- `docs/kite-0.9-architecture-program.md`
- `src/kite/application/`
