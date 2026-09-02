# Kite v0.8.1 — Dashboard, credentials, agent hardening

**Date:** 2026-09-01

## Highlights

**0.8.1** builds on [v0.8.0](RELEASE-0.8.0.md) with a **per-user session dashboard**, **long-task mode**, **BYOK/BYOS credential UX**, **Context7 docs tools**, **mandatory approval for high-risk commands**, **smarter agent completion**, and **token-efficient** tool prompts.

---

## Session dashboard

```bash
kite dashboard              # overview — sessions, tools, tokens, cache, cost
kite dashboard --session ID # drill into one run (timeline, failures, verification)
kite dashboard --watch 5    # refresh every 5s
kite dashboard --json       # machine-readable
```

Reads `~/.kite/sessions/` JSONL + stats sidecars for **your** machine only.

---

## BYOK / BYOS credentials

| Type | Examples | Command | Storage |
|------|----------|---------|---------|
| **BYOK** | `groq`, `openai`, `anthropic` | `kite login groq` | `~/.kite/.env` |
| **BYOS** | `chatgpt`, `claude`, `grok` | `kite login chatgpt` | `~/.kite/oauth/` |

- New keys: **double-entry**, validation, masked fingerprint (`••••abcd`)
- `/keys` and `kite keys` — type column (BYOK/BYOS), OAuth `linked` / `login required`
- BYOS login **opens a browser** and shows a device code (ChatGPT) or in-browser sign-in (Grok); Claude can paste `claude setup-token`
- Model choice in `~/.kite/config.toml` — not `.env`

---

## Agent safety & completion

- **Mandatory approval** — `sudo`, `rm`, package installs, `git commit/push`, `curl`, etc. always prompt (no yolo bypass)
- **Git reads** — `git status`, `log`, `diff` run without prompts; writes still gated
- **Completion** — agent must not claim done early; idle turns that narrate success are blocked; consecutive failed tools get a “don’t claim done” nudge
- **Submit gate** (from 0.8.0) — evidence required before declaring success

---

## Context7 & session time

Built-in library docs via Context7 HTTP tools (`context7_resolve`, `context7_docs`). Optional `CONTEXT7_API_KEY` in `~/.kite/.env`. System prompt includes session UTC + local time.

---

## Long-task mode

```bash
kite run --long "refactor auth module"
kite chat --long
```

Higher limits, periodic checkpoints, `mode_long.md` guidance.

---

## Memory & `/help`

- **Semantic** — `~/.kite/memory/MEMORY.md` + project `.kite/MEMORY.md`
- **Episodic** — sqlite episode log under `~/.kite/memory/`
- `/forget` removes matching notes **and** episodes
- `/help` lists canonical commands + **legacy aliases** (`/select` → `/model select`, `/cost` → `/status`, …)

---

## Upgrade

```bash
./scripts/pkg.sh update       # git pull + editable reinstall (existing checkout)
# or first-time / fresh venv:
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.8.1
```

Reinstall or remove the package (keeps `~/.kite/`):

```bash
./scripts/pkg.sh reinstall
./scripts/pkg.sh uninstall          # pip uninstall only
./scripts/pkg.sh uninstall --remove-venv
```

```bash
kite setup              # guided wizard
kite login groq         # BYOK
kite login chatgpt      # BYOS OAuth
kite dashboard          # your local stats
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.8.1] entry.
