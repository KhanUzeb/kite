# Kite v0.9.5

**Date:** 2026-09-07

## Highlights

- **Pi-style runtime** — mid-turn steering injects user corrections and continues the same run; follow-ups queue at turn boundaries; `compaction_start` / `compaction_end` events.
- **Busy REPL UX** — message inbox (Enter queue · Ctrl+G steer · Ctrl+U dequeue), steer/follow-up labels, live activity preview, stable streaming TUI (no composer respam).
- **Session browser** — `kite sessions` shows date/time/title; filter with `kite sessions -q`; `kite resume <id>` with prefix match and suggestions.
- **Agent skills** — loads `~/.agents/skills` on any machine (alongside `~/.kite/skills`).
- **Lower resource use** — bounded file reads, session rewrite on compact, TTL cache caps, job/checkpoint pruning, capped repo-map walks.
- **Harness timing** — `kite bench` covers 18 startup/context/tool cases; `kite bench --check` and `tests/test_bench.py` enforce CI budgets.
- **Faster cold start** — REPL banner skips `resolve_model` until the first task.
- **Leaner test suite** — ~330 focused tests (down from ~540); merged helper modules; bench and runtime coverage.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite bench --check
kite --version   # 0.9.5
```

## Sessions

```bash
kite sessions                  # dated table + picker
kite sessions humanize         # filter by title/cwd/id
kite resume <id>               # open in chat (prefix ok)
kite resume <id> "continue"    # one-shot follow-up
```

## Harness timing

```bash
kite bench                 # median ms per case (no LLM)
kite bench --check         # fail if over budget (CI)
pytest tests/test_bench.py -q
```

Budgets: `src/kite/bench/budgets.py`.

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.5] entry.
