# Kite v0.7.0 — Harness upgrade release

**Date:** 2026-08-31

## Highlights

Kite 0.7 is a harness-focused release: measurable performance (`kite bench`), safer execution context, richer tool contracts, long-horizon session continuity, and a faster REPL cold start.

## New commands

```bash
kite bench [--json] [--save PATH] [--compare BASELINE.json]
```

REPL: `/checkpoint save|list|restore|show` · `/handoff [dir]`

## Harness features

| Feature | What it does |
|---------|----------------|
| `kite bench` | Timing baseline for startup, context, tools — no live LLM |
| `set_cwd` | Change session working directory for file tools + bash |
| `execution_mode` | `restricted` (default) or `host` in runtime config |
| `ToolResult` | Structured tool outcomes + metadata |
| Parallel reads | Concurrent safe read-only tools in one turn |
| Bash cancel | Interrupt long bash without killing the REPL |
| Context checkpoints | Auto snapshot ~72% ctx; manual save/restore |
| `/handoff` | Export session brief for another agent |
| Lazy REPL init | Model resolve deferred until first message |

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite bench --json
```

## Benchmark validation

```bash
# optional: compare against a pre-upgrade baseline
kite bench --save /tmp/before-0.6.8.json
# after upgrade
kite bench --compare /tmp/before-0.6.8.json
```

## Breaking changes

None intended. Host mode is opt-in via `[guardrails] execution_mode = "host"`.

## What's next (Phase 2)

1. Tool cards UI + stream coalescing
2. Fuzzy edits + smarter verification
3. Repo map + relevance ranking
4. Dedicated PowerShell tool
