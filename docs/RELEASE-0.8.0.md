# Kite v0.8.0 — BYOS subscriptions, approval modes, verification gate

**Date:** 2026-09-01

## Highlights

**0.8.0** adds **subscription OAuth** (ChatGPT, Claude, Grok), clearer **approval modes** (`yolo` / `auto` / `supervised`), an enforced **submit verification gate**, smarter **token compaction**, and **anti-hallucination** loop detection. BYOK providers keep API-key login; subscription providers use OAuth and live model lists.

---

## BYOS (Bring Your Own Subscription)

| Provider | Login | Default model |
|----------|-------|---------------|
| `chatgpt` / `codex` | `kite keys --set chatgpt` or `/login chatgpt` | `gpt-5.6-luna` |
| `claude` / `claude-sub` | `kite keys --set claude` or `/login claude` | `claude-opus-5` |
| `grok` / `grok-sub` | `kite keys --set grok` or `/login grok` | `grok-4.6` |

Tokens live under `~/.kite/oauth/`. Models are fetched live (5-minute cache), not hardcoded.

---

## Approval modes

| Mode | Behavior |
|------|----------|
| **yolo** | No approval prompts |
| **auto** | Auto inside workspace; ask for paths/bash outside project root |
| **supervised** | Reads free; every mutating tool needs approval |

Set via `--approval yolo|auto|supervised` or `/approve` in the REPL.

---

## Verification & anti-hallucination

- Submit is **blocked** when code was edited without a recorded passing test/lint run
- Failed tests block submit
- Unfounded “tests pass” claims in the summary are rejected
- `## Verification` section with `✓` items required when files changed
- Loop guard: progress reset on changed output; hard-stop after 5 identical repeats

Disable enforcement: `[agent] verify_before_submit = false` in runtime config.

---

## Token optimizations

- Compact at **80%** context (`compaction_ratio`)
- Skip slow LLM summarization below **92%** — deterministic path is default-fast
- Tool-pair-safe compaction keeps `tool_calls` + `tool` results grouped
- Summary-aware elision for large tool outputs (`observation_max_chars = 8000`)

---

## Other

- **Durable session events** in JSONL alongside messages
- **Subagent timeout** — `orchestrator_timeout_seconds = 300` (configurable)
- **`api_styles`** — per-provider `chat` | `messages` | `responses` hint (adapter wiring is thin; deeper Responses API work follows)

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.8.0
```

Link a subscription:

```bash
kite keys --set chatgpt   # or claude / grok — opens OAuth flow
kite models -p chatgpt --select
```

---

## Breaking / behavior changes

- **Submit gate** — agents can no longer claim “done” after edits without running checks (unless `verify_before_submit = false`).
- **Default bash output cap** — 32k chars (was 100k); override in `[guardrails] max_bash_output_chars`.
- **Compaction** — triggers at 80% context ratio by default (was ~87% reserve-only).

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.8.0] entry.
