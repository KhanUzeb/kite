# Kite v0.9.9

**Date:** 2026-09-15

## Highlights

- **Harness parity upgrade** — the agent loop, orchestration, memory, and context
  layers are rebuilt from Codex / Pi / Claude-Code learnings: pre-tool budget
  guards, schema-repair nudges, summed multi-turn cost accounting, a wired
  verification gate on `submit`, stable-prefix prompt caching, role-based
  subagent model tiers (`fast` / `coder` / `smart`), per-profile tool scopes,
  depth + spawn budgets, context packets, bounded summaries, a quality gate
  with one-shot revise, a thread-tree task registry, `abort_on_failure`, and
  per-worker timeouts.
- **Resume that works** — `kite resume <id>` renders the full chronological
  transcript (user, assistant, tool calls/results, submit events) and restores
  context; every interactive exit prints a copy-pasteable
  `kite resume <session-id>` hint (#83, #84).
- **Informational answers stay answers** — Q&A turns keep the assistant's
  content; the `Done / Changed / Verification` report becomes an adjunct or is
  suppressed when nothing changed (#81).
- **Lean CLI only** — the optional Textual TUI is removed; Rich +
  prompt_toolkit REPL is the single interface. `/fullscreen` is retired.
- **Faster, split CI** — lint / test / bench / release-check jobs,
  `fail-fast: false`, `sync_version --check` fast path for PRs with full
  release checks on tags only.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.9
```

Windows: `.\scripts\install.ps1`.

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.9] entry.
