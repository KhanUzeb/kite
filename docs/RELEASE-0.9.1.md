# Kite v0.9.1

**Date:** 2026-09-06

Patch release on the 0.9 line: longer interactive turns with capped budget
auto-continue, Codex/Pi-style continuity memory across compact/resume, and UI
fixes so `/compact` and the busy composer behave reliably.

## Highlights

- **Interactive budget floors** — chat defaults to ~80 steps / $10 when still on
  package defaults (40 / $5); explicit lower user caps are honored.
  Non-interactive `kite run` unchanged unless flags say otherwise.
- **Adaptive auto-continue** — on `LimitsExceeded` with unfinished work (open
  todos), auto-resume up to **2** times with a continuity brief
  (`budget continue N/2 — resuming…`), then soft-pause. Inbox queue wins over
  silent continue. LoopGuard / idle stall / interrupt still block spirals.
- **Continuity memory** — structured mission/done/next/todos briefs stored as
  episodic `continuity` episodes after compact or before budget continue;
  injected into the next turn; optional project MEMORY pin for paths/constraints.
- **Earlier auto-compact** — default `compaction_ratio` **0.75** (checkpoint
  still ~72%).
- **Busy composer** — stderr WaitSpinner no longer overwrites the pinned input
  while working; activity stays on the toolbar running line.
- **LimitsExceeded UX** — soft pause with continue hint instead of
  `LimitsExceeded: LimitsExceeded`.
- **`/compact` (and siblings)** — slash dispatch args fixed (`TypeError` gone).

Also includes post-0.9.0 harness work already on `main`: structured `submit`,
git-ranked repo map, ToolExecutor cutover, live verification footer, replay
acceptance.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
# Windows: .\scripts\install.ps1
pytest -q
kite --version   # 0.9.1
```

## Testing

```bash
pytest -q
python scripts/sync_version.py --check
```

CI runs Linux + Windows on Python 3.11 and 3.12.

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.1] entry.
