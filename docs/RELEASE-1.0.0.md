# Kite v1.0.0

**Date:** 2026-09-20

## Highlights

- **Project bootstrap (MiniMax-style)** — `kite init` and REPL `/init` scaffold
  `AGENTS.md`, skills, and verification hints; `examples/clamp` demo;
  `/context` and `/status` digests; shared `resolve_verification_command()` for
  CI and workspace profiles (#96).
- **SoL-Pi harness (opt-in)** — optional Action Fusion, ObservationPack,
  Evidence-Preserving Reducer validation, and Online Context Compact wired
  through harness hooks. All mechanisms stay **off** unless enabled in
  `.kite/sol-pi.json` or `~/.kite/sol-pi.json` (#97).
- **1.0 milestone** — bootstrap + efficiency layer on the hardened 0.9.x
  guardrails, resume, and orchestration stack.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.0
```

Windows: `.\scripts\install.ps1`.

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.0] entry.
