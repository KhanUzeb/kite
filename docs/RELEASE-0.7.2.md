# Kite v0.7.2 — Sandbox UX, REPL polish, MCP removal

**Date:** 2026-08-31

## Highlights

**0.7.2** fixes cold-start crashes, lets `set_cwd` leave the project root, defaults to **host** filesystem access (with `/restricted on` when you want a tighter sandbox), adds mouse-wheel slash completion, and refreshes the ctx meter after compaction. Stdio **MCP** is removed; inject tools via `Harness.extra_tools` instead.

---

## REPL

| Feature | What it does |
|---------|----------------|
| `/restricted on\|off` | Toggle path sandbox (default **off** = host mode) |
| `/sandbox` | Alias for `/restricted` |
| Slash menu scroll | Mouse wheel (and scroll keys) on `/` completions |
| `/compact` ctx meter | Footer ctx % updates right after compaction |
| Auto-compact ctx | Compaction boundary shows `N → M · ctx XX%` |

---

## Guardrails & execution

| Change | Detail |
|--------|--------|
| Default mode | `execution_mode = "host"` in runtime TOML |
| `set_cwd` | May target paths outside `project_root`; sandbox follows `execution_cwd` |
| Protected paths | `.ssh`, system dirs, `.env`, etc. still blocked in both modes |

---

## Removed

- **MCP stdio client** and `[[mcp]]` in `default.toml`
- Use **`Harness.extra_tools`** or project plugins for custom tools

---

## Fixes

- **`kite` with no args** no longer crashes on `os.stdin.isatty()`
- **Runtime** — simpler tool assembly; audit listener attached once

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.7.2
```

Want the old default sandbox? Run `/restricted on` in the REPL, or set `[guardrails] execution_mode = "restricted"` in your runtime config.

---

## Breaking changes

- **MCP config ignored** — remove `[[mcp]]` blocks; they are no longer loaded.
- **Default sandbox is host mode** — file tools can reach outside the session cwd unless you opt into `/restricted on` or `execution_mode = "restricted"`.

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the 0.7.2 entry.
