# Kite v1.0.1

**Date:** 2026-09-22

## Highlights

- **Antigravity OAuth** — `kite login antigravity` links a Google
  subscription through the official `agy` CLI (local browser flow or the
  SSH manual URL loop). Status/logout, catalog entry, and fallback Gemini
  models included; model calls use `GEMINI_API_KEY`, same split as the
  Claude Code subscription.
- **Composer fold** — long pastes collapse to first lines + `+N lines`;
  any key expands, `Enter` always submits the full text, `F9` toggles.
- **Steering that continues** — mid-turn corrections interrupt the agent
  but keep the pinned composer alive instead of stopping the session.
- **Metering that meters** — cost falls back to usage-based pricing when
  providers omit `response_cost`; the footer leaves $0.000 behind.
- **Plan mode acts** — `/plan <text>` and `/build <text>` start work
  immediately; bare `/plan` reports a resumed checklist.
- **Leaner suite, same coverage** — tests consolidated 425 → ~217 with
  every assertion preserved; `examples/clamp` untracked and purged.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.1
```

Windows: `.\scripts\install.ps1`. Global CLI: `uv tool upgrade kite`.

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.1] entry.
