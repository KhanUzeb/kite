# Kite v0.9.8.5

**Date:** 2026-09-13

## Highlights

- **Lean CLI** is the product. Interactive `kite` is a Pi-style scrollback REPL (header, composer, footer) — not a fullscreen TUI.
- **Every subcommand is listed** in `kite --help` and works (maintainer dashboard stays hidden / gated).
- **Pi habits:** `kite -c` continue last session, `kite -r` browse sessions, `!cmd` / `!!cmd` in the composer, `/hotkeys`, opening prompts (`kite fix the tests`).
- Textual TUI is optional: `uv pip install "kite[tui]"` then `KITE_TUI=1`.
- **Pick/select** (models, providers, sessions) stay on a console list: arrows or a number + Enter. CI uses `KITE_TYPED_PICK=1` so pytest never opens a live picker.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.8.5
kite --help
```

Windows: `.\scripts\install.ps1`.

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.8.5] entry.
