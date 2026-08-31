# Kite v0.7.1 — Harness upgrade + onboarding + UI polish

**Date:** 2026-08-31

## Highlights

Kite 0.7 is a major harness release. **0.7.1** consolidates the harness upgrade (bench, execution context, checkpoints, handoff), adds **tool cards UI**, improves **new-user onboarding**, and tightens **CI**.

If you are upgrading from **0.6.x**, read both the 0.7.0 harness section and the 0.7.1 polish below.

---

## New commands

```bash
kite bench [--json] [--save PATH] [--compare BASELINE.json]
kite help                    # grouped CLI quick reference
kite setup                   # first-run wizard (also offered on bare `kite`)
```

REPL: `/setup` · `/checkpoint save|list|restore|show` · `/handoff [dir]`

---

## Harness (0.7.0)

| Feature | What it does |
|---------|----------------|
| `kite bench` | Timing baseline — no live LLM |
| `set_cwd` | Session working directory for file tools + bash |
| `execution_mode` | `restricted` (default) or `host` in runtime config |
| `ToolResult` | Structured tool outcomes + metadata |
| Parallel reads | Concurrent safe read-only tools in one turn |
| Bash cancel | Interrupt long bash without killing the REPL |
| Context checkpoints | Auto snapshot ~72% ctx; manual save/restore |
| `/handoff` | Export session brief for another agent |
| Lazy REPL init | Model resolve deferred until first message |

---

## Onboarding & UI (0.7.1)

| Feature | What it does |
|---------|----------------|
| `/setup` + first-run prompt | Guided API key + model picker |
| Readiness checks | `kite providers` / `kite keys` show ready status |
| Tool cards | `▸ read  path` in-flight; `✓ edit  +2,-1` on done |
| Stream coalescing | Less flicker on fast model streams |
| `kite help` | Short grouped CLI map |

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
# optional: guided setup
./scripts/install.sh --no-clone --setup
pytest -q
kite bench --json
```

Skip the setup prompt in automation: `export KITE_SKIP_SETUP=1`

---

## Benchmark validation

```bash
kite bench --save /tmp/before.json
# after upgrade
kite bench --compare /tmp/before.json
```

---

## Breaking changes

- **MCP removed** — `[[mcp]]` / `mcp_servers` in runtime TOML no longer spawn stdio servers. Register custom tools via `Harness.extra_tools` or `.kite/extensions/*.py` (`ExtensionAPI.register_tool`).
- Host mode remains opt-in via `[guardrails] execution_mode = "host"`.

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for 0.7.1 and 0.7.0 entries.
