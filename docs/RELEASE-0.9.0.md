# Kite 0.9 Release Notes (in progress)

Kite 0.9 introduces a new **application layer** with stable harness contracts
while keeping 0.8 CLI/REPL behavior through compatibility adapters.

## Milestones A–H

| Commit milestone | Capability |
|----------------|------------|
| A | `RunSpec`, `EventEnvelope`, `ApplicationRunService`, CI matrix |
| B | `ContextAssembler`, budgets, provenance, compaction state |
| C | `PolicyEngine`, `ToolExecutor`, `ChangeJournal`, `ProcessRunner` |
| D | `SQLiteEventStore`, redaction, resume reconstruction |
| E | `ModelGateway`, typed retries, `BudgetLedger` |
| F | `EvidenceVerifier` — verification from tool results only |
| G | `CliResult` exit codes, `ReplEventReducer` |
| H | `ReplayBundle` recorded replay without live providers |

## Migration notes

- **Restricted mode** remains the safe default; host mode is explicit.
- Legacy `Harness.run()` continues to work; new code should prefer
  `ApplicationRunService.run(RunSpec)`.
- JSONL sessions remain supported; SQLite is the canonical store for new runs.

## Testing

```bash
pytest -q
uv run ruff check src tests
```

CI runs Linux + Windows on Python 3.11 and 3.12.
