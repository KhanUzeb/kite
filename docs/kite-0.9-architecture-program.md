# Kite 0.9 architecture program

**Status:** adapters landed; production CLI/REPL still uses `Harness` → `AgentRuntime` → `DefaultAgent`.

See [RELEASE-0.9.0.md](RELEASE-0.9.0.md) for the milestone table. This stub restores the link referenced from AGENTS.md and README.

## Milestones A–H (summary)

| Milestone | Capability | Production status |
|-----------|------------|-------------------|
| A | `RunSpec`, `EventEnvelope`, `ApplicationRunService`, CI matrix | Adapter + CI |
| B | `ContextAssembler`, budgets, provenance | Adapter |
| C | `PolicyEngine`, `ToolExecutor`, `ChangeJournal`, `ProcessRunner` | **Loop cutover** |
| D | `SQLiteEventStore`, redaction, resume reconstruction | Adapter (JSONL still live) |
| E | `ModelGateway`, typed retries, `BudgetLedger` | Adapter |
| F | `EvidenceVerifier` + artifact-aware collector | **Production submit gate** |
| G | `CliResult` exit codes, `ReplEventReducer` | Adapter |
| H | `ReplayBundle` + acceptance criteria | **Eval without live providers** |

## 1.0 deferrals

- SQLite sessions as canonical store
- `ModelGateway` / `ContextAssembler` as primary entry
- Retiring `Harness` in favor of `ApplicationRunService` only

## Related

- [ADR 0001](adr/0001-application-harness-seam.md)
- [kite-system-design.md](kite-system-design.md)
