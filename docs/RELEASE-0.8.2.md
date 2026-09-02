# Kite v0.8.2

**Date:** 2026-09-02

## Highlights

0.8.2 builds on [v0.8.1](RELEASE-0.8.1.md) with a unified background job registry (bash + subagents), busy stop/steer chrome, left-bar pickers, plan/build checklist handoff, new bundled skills, stricter submit evidence, SYSTEM.md overrides, and package maintenance scripts.

---

## Background jobs (`/jobs` / `/kill`)

One `JobRegistry` per session tracks:

- bash started with `background=true` (long servers, watches)
- live `subagent` workers from the orchestrator

| Command | Effect |
|---------|--------|
| `/jobs` | List active jobs; pick one to kill |
| `/kill id` | Kill that job or subagent |
| `/kill all` | Kill every active background job |

Footer shows `jobs N`. Quitting the REPL kills remaining jobs.

---

## Busy composer (stop / steer / queue)

While a turn runs, the composer stays live:

| Action | How |
|--------|-----|
| Stop | Esc, Ctrl+C, or `/stop` (session stays open) |
| Steer | Ctrl+G or `/steer text` (stop, then run that text next) |
| Queue | Enter while working (slash commands wait until the turn ends) |

Busy chrome lives on the composer and footer only. Agent SIGINT handling stays on the main thread.

---

## Left-bar pickers

TTY menus for empty `/approve`, `/theme`, `/font`, `/reasoning`, `/restricted`, `/resume`, `/sessions`, `/logout`, `/skills`, plus CLI `kite sessions`, `kite resume`, `kite models`, `kite providers`, `kite keys`, and `kite skills`. Type a number, id, or empty to cancel. No right-hand sidebar.

Mouse capture stays off by default. Optional `KITE_MOUSE=1` for slash-menu wheel scroll. Composer clipboard: Ctrl+V / Shift+Insert paste, Ctrl+Insert copy.

---

## Plan mode and skills

- `/plan` explores with inspection bash + read-only tools; writes a checklist; notes risks and open questions; does not submit-as-done.
- `/build` keeps that checklist and applies it.
- New bundled skills: `/orchestrate`, `/research`, `/pr` (plus existing commit/debug/review/test).
- Thinking traces stream expanded by default (`Ctrl+T` / `/expand-thinking collapse` to fold).

---

## System prompt overrides

| File | Effect |
|------|--------|
| `.kite/SYSTEM.md` or `~/.kite/SYSTEM.md` | Replace the bundled base prompt (project wins) |
| `.kite/APPEND_SYSTEM.md` or `~/.kite/APPEND_SYSTEM.md` | Append after the base (project wins) |

Harness `--system-prompt` / config still beats discovered `SYSTEM.md`.

---

## Verification

Submit blocks narrated "done" / "tests pass" when no passing check was recorded. Latest test artifact wins (a later pass clears an earlier failure gap).

---

## Package scripts

```bash
./scripts/pkg.sh update       # git pull + editable reinstall
./scripts/pkg.sh reinstall
./scripts/pkg.sh uninstall    # optional --remove-venv
# Windows: .\scripts\pkg.ps1 update|reinstall|uninstall
```

---

## Upgrade

```bash
./scripts/pkg.sh update
# or:
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.8.2
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.8.2] entry.
