# Kite v0.9.2

**Date:** 2026-09-06

Daily-driver release: opt-in memory, verify-over-stall completion, sharper web
research tools, and REPL UX polish (approval chrome, verification footer, `@`
completion).

## Highlights

- **Verify over stall** — build mode with unverified edits gets nudges and a
  suggested check command instead of idle stall after two quiet turns.
- **Opt-in memory** — MEMORY.md / episodic sqlite only inject when you ask
  (`/remember`, `/memory`, or `[memory] inject = "always"`). Continuity briefs
  after compact/budget-continue stay separate working state.
- **Web research** — `webfetch` returns extracted text + title (not raw HTML);
  `websearch` unwraps redirect links, dedupes results, and falls back when DDG
  layout shifts; localhost/private URLs blocked.
- **REPL UX** — approval footer shows `[a] once · [n] deny · [q] stop`;
  persistent verification badge; cost warnings on toolbar during busy composer;
  `@file` path completion; Tab cycles completions.
- **Tooling** — fuzzy `edit` whitespace fallback; compaction keeps edited-path
  facts; blocked submit surfaces next verification command.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
# Windows: .\scripts\install.ps1
pytest -q
kite --version   # 0.9.2
```

## Testing

```bash
pytest -q
python scripts/sync_version.py --check
```

CI runs Linux + Windows on Python 3.11 and 3.12.

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.2] entry.
