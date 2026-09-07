# Kite v0.9.3

**Date:** 2026-09-06

Patch fix: stop greeting-only model replies from falsely completing coding tasks.

## Highlights

- **Completion keyed on user intent** — `hi` / thanks → text reply ends the turn.  
  `lower number of tests` + model says only `Hey! 👋` → **idle nudge**, not `✓ work complete`.
- **Documented harness rules** — decision table in system prompt, `CONTEXT.md`, and `kite_commands.md`.
- Footer running line clears when the turn ends.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.3
```

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.3] entry.
