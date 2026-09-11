# Kite v0.9.7

**Date:** 2026-09-11

## Highlights

- **Flatter source** — 0.9 contracts live as modules (`execution.py`, `policy.py`, `cli.py`, …), plus `eval.py`, `tasks.py`, and `plugins/extensions.py`. Import names did not change.
- **Leaner checkout** — pytest is ~174 domain tests; scripts are install/download/sync/bump only; docs keep architecture, glossary, commands, security, and this file.
- **Honest headless** — `kite run --headless`, `kite exec`, and `kite tasks` exit 0 only after a real submit and leftover job teardown.
- **Faster, quieter startup** — CLI and config skip heavy imports until needed; REPL blank Enter does nothing; setup banner no longer false-alarms on an empty catalog default.
- **Credentials** — Claude login copy says you still need `ANTHROPIC_API_KEY`; Codex/ChatGPT BYOS flattens tokens for LiteLLM.
- **Paid web backends** — optional Tavily / Exa / Firecrawl keys via `kite web-keys`.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.7
```

Windows: `.\scripts\install.ps1`. Global CLI: `uv tool upgrade kite`.

## Headless

```bash
kite exec "fix the failing test"
kite tasks run tasks.jsonl --steps 40
kite run --headless "fix the failing test"
```

Success means `Submitted` and no leftover jobs. Unfinished work is a non-zero exit.

## Help

```bash
kite help
# REPL: /help
```

Lists `kite_commands.md`, `CONTEXT.md`, `architecture.md`, `SECURITY.md`, and `docs/RELEASE-0.9.7.md`.

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.7] entry.
