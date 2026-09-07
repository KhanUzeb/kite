# Kite v0.9.4

**Date:** 2026-09-07

## Highlights

- **Live terminal (`/live`)** — stream bash and background-job output as commands run (toggle in the REPL).
- **Auto venv** — detects `.venv` / `venv` with `pyvenv.cfg` and prepends it to bash `PATH` so `python`, `pip`, and `pytest` use the project environment.
- **Security & reliability** (since v0.9.3) — SSRF hardening, env-filter for child processes, REPL freeze fixes, composer approval keys, token budget defaults, SQLite locking, and expanded CI gates.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.4
```

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.4] entry.
