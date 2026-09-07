# Kite v0.9.4

**Date:** 2026-09-07

## Highlights

- **Live terminal (`/live`)** — stream bash and background-job output as commands run (toggle in the REPL).
- **Auto venv** — detects `.venv` / `venv` with `pyvenv.cfg` and prepends it to bash `PATH` so `python`, `pip`, and `pytest` use the project environment.
- **Harness timing** — `kite bench` measures startup, context, and tool latency without a live LLM; `--check` enforces budgets in CI.
- **Faster cold start** — REPL banner skips model resolution until the first task.
- **Lower resource use** — bounded file reads, session rewrite on compact, cache/job/checkpoint caps.
- **Security & reliability** (since v0.9.3) — SSRF hardening, env-filter for child processes, REPL freeze fixes, composer approval keys, token budget defaults, SQLite locking, and expanded CI gates.

## Harness timing (`kite bench`)

No API keys required. Median wall time per case:

```bash
kite bench
kite bench --check              # exit 1 if over budget (CI)
kite bench --save before.json
kite bench --compare before.json
pytest tests/test_bench.py -q   # same budgets in unit tests
```

| Category | What it measures |
|----------|------------------|
| **startup** | CLI import, config/catalog load, skills, REPL init, model resolve, slash index, runtime `prepare()` |
| **context** | Repo map, project context gather, prompt assembly, prompt-cache manager |
| **tools** | Tool registry build, read/grep/bash, subprocess spawn |

Budgets: `src/kite/bench/budgets.py`.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite bench --check
kite --version   # 0.9.4
```

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.4] and [Unreleased] entries.
