# Kite v0.9.8

**Date:** 2026-09-13

## Highlights

- Ask for a crew or name a subagent profile in plain language. The system prompt now tells the main agent to call `subagent` instead of faking it in bash. Per-worker `model=` and `provider=` overrides (plus crew arrays) ride through the orchestrator.
- Project trust works like Pi: `~/.kite/trust.json`, `/trust`, or `trust = true` in `.kite/project.toml`. Trusted workspaces skip nested-agent approval prompts.
- On REPL startup Kite checks GitHub for a newer release (24h cache). Set `KITE_OFFLINE=1` to skip.
- Textual picks up a few Antigravity habits: `Ctrl+K` for fast-path approval, `Ctrl+J` for the agents panel, and slower poll timers so idle sessions use less CPU.
- Harness is faster on repeat turns: cached model metadata, static `prepare()` (project context + skills), compaction skips re-serializing tool schemas, and a reused thread pool for parallel tool batches.
- Textual 8 theme application no longer calls removed `Stylesheet.clear()` — the TUI mounts and the harness runs.
- Harness bench budgets are a bit tighter. Textual refreshes the sidebar and status line less often.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.8
```

Windows: `.\scripts\install.ps1`. Global CLI: `uv tool upgrade kite`.

## Project trust

```bash
/trust on          # trust cwd — nested agents skip extra approval
/trust status
```

Or in `.kite/project.toml`:

```toml
[project]
trust = true
```

## Help

```bash
kite help
# REPL: /help
```

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.8] entry.
