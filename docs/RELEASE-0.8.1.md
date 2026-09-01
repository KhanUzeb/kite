# Kite v0.8.1 — Dashboard, long sessions, credential UX, provider retry

**Date:** 2026-09-01

## Highlights

**0.8.1** builds on [v0.8.0](RELEASE-0.8.0.md) with a **session dashboard**, **long-task mode**, **token-efficient tool prompts**, **REPL UI polish**, **recoverable provider retry**, and clearer **BYOK vs BYOS** credential flows (`kite login`, `/keys` OAuth status, setup wizard).

---

## Session dashboard

```bash
kite dashboard              # overview — sessions, tools, tokens, cache, cost
kite dashboard --session ID # drill into one run
kite dashboard --watch 5    # refresh every 5s
kite dashboard --json       # machine-readable
```

Scans local JSONL sessions + stats sidecars under `~/.kite/sessions/`.

---

## Long-task mode

```bash
kite run --long "refactor auth module"
kite chat --long
```

Higher step/cost limits, periodic phase checkpoints, and `mode_long.md` system guidance for multi-hour work.

---

## BYOK / BYOS credentials

| Type | Examples | Command | Storage |
|------|----------|---------|---------|
| **BYOK** | `groq`, `openai`, `anthropic` | `kite login groq` or `kite keys --set groq` | `~/.kite/.env` |
| **BYOS** | `chatgpt`, `claude`, `grok` | `kite login chatgpt` or `/login chatgpt` | `~/.kite/oauth/` |

- **`/keys`** and **`kite keys`** show `linked` / `login required` for OAuth
- **Setup wizard** explains both paths and triggers OAuth when you pick a subscription provider
- **Model choice** stays in `~/.kite/config.toml` — not in `.env`

---

## Token-efficient tools

Prompts favor **bash-first** inspection (`rg`, `head`, `sed -n`) over full-file `read`. `read` returns raw content by default (`numbered=true` optional). Plan mode allows read-only inspection bash.

---

## REPL UI

- Thinking **collapsed by default** — `/expand-thinking` or **Ctrl+T**
- Unified **approval panel** (left bar); no duplicate “waiting for OK” line
- **Terminal-style bash** blocks in tool cards
- **Colourful task list** with progress bar

---

## Provider retry

Transient network/provider errors retry with exponential backoff (`provider_max_retries`, default 4). On exhaustion the session is **saved** — send another message or `kite resume <id>` to continue.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.8.1
```

Link credentials:

```bash
kite login groq       # BYOK — hidden key
kite login chatgpt    # BYOS — OAuth subscription
kite setup            # guided wizard (both paths)
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.8.1] entry.
