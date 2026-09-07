# Kite v0.9.0

**Date:** 2026-09-04

Kite 0.9 introduces a tested **application layer** (`RunSpec`, `EventEnvelope`,
`ApplicationRunService`) while keeping 0.8 CLI/REPL behavior through
compatibility adapters. Production chat still runs `Harness` → `AgentRuntime`
→ `DefaultAgent`. New code should prefer `ApplicationRunService.run(RunSpec)`.

## Highlights

- Canonical contracts for context, policy, persistence, model retries, evidence,
  CLI results, and recorded replay (milestones A–H).
- **Production harness improvements** (post-release on `main`): `ToolExecutor`
  wired into the agent loop; structured `submit` tool; git-ranked repo map;
  `EvidenceVerifier` in the verification collector; `ReplayBundle` acceptance
  criteria; live `verification_status` in the REPL footer.
- Pinned busy composer: type a follow-up while a turn runs; `/tasks`; footer
  **tok/s** and **cache hit**.
- Global skill library: install npm/git packs into `~/.kite/skills`, or
  **link** a local folder (`/skills add ./my-skill`). Windows uses a directory
  junction when a symlink is refused. Restricted mode can read that library.

## Milestones A–H

| Milestone | Capability | Production status |
|-----------|------------|-------------------|
| A | `RunSpec`, `EventEnvelope`, `ApplicationRunService`, CI matrix | Adapter + CI |
| B | `ContextAssembler`, budgets, provenance | Adapter |
| C | `PolicyEngine`, `ToolExecutor`, `ChangeJournal`, `ProcessRunner` | **Loop cutover** (guardrails bash layer retained) |
| D | `SQLiteEventStore`, redaction, resume reconstruction | Adapter (JSONL still live) |
| E | `ModelGateway`, typed retries, `BudgetLedger` | Adapter |
| F | `EvidenceVerifier` + artifact-aware collector | **Production submit gate** |
| G | `CliResult` exit codes, `ReplEventReducer` | `ApplicationRunService` entry; legacy REPL events |
| H | `ReplayBundle` + acceptance criteria | **Eval without live providers** |

## Skills

```text
/skills add @scope/pkg
/skills add owner/repo
/skills add ./my-skill
/skills add ~/code/hatch-pet
kite skills --add C:\Users\me\.codex\skills\hatch-pet
```

Each install also links `.kite/skills/<name>` → `~/.kite/skills/<name>` in the
current project. Reinstall removes the link, not the real files.

## Migration notes

- Packaged **execution mode stays `host`** (same as 0.8). `PolicyEngine`
  defaults to **restricted** when used as the new seam. Host still blocks
  protected paths.
- Legacy `Harness.run()` continues to work.
- JSONL sessions remain the production store. SQLite is an event-store adapter,
  not yet canonical for new CLI/REPL runs.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
# Windows: .\scripts\install.ps1
pytest -q
kite --version   # 0.9.0
```

## Testing

```bash
pytest -q
uv run ruff check src/kite/application src/kite/eval
python scripts/sync_version.py --check
```

CI runs Linux + Windows on Python 3.11 and 3.12.

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.0] entry.

Architecture: [architecture.md](../architecture.md) and [kite-system-design.md](kite-system-design.md).
