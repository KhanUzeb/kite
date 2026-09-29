# Kite v1.0.3

**Date:** 2026-09-29

## Highlights

Thinking variants go first-class (`kite variants` / `/variants`, strictly
limited to what your model supports, shown as `provider/model#variant`),
the model can now ask you clarifying questions mid-turn (opencode-style
`question` tool), Antigravity subscriptions answer through your signed-in
`agy` CLI without an API key, and the terminal UI compacts itself inside
Orca relay sessions. Theme pickers are typed-only now — no more frozen
option lists or stray escape bytes.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.3
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.3] entry.
