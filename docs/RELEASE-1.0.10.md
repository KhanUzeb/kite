# Kite v1.0.10

**Date:** 2026-11-01

## Highlights

A reliability and continuity release. Provider prompt-cache payloads now stay on compatible routes; failed LiteLLM prewarm imports can retry; sessions can be forked; and bundled defaults no longer block ordinary `git push` before its approval gate.

## Provider and cache reliability

- Anthropic `cache_control` content blocks are sent only to Anthropic-compatible routes. OpenRouter, Azure, Bedrock, and Vertex requests keep their ordinary text content.
- Cache-hit ratios use normalized input totals without double-counting cache-creation tokens.
- A failed background LiteLLM import clears its prewarm handle so the next call can retry.

## Sessions and subagents

- `kite sessions --fork <id>` creates a new session containing the source conversation and current provider/model/reasoning settings. It does not copy source audit events, checkpoints, or sidecars.
- Unknown subagent profiles now suggest close matches; profile details show model and tool settings.
- The bundled system prompt documents scoped-worker write boundaries and uses Kite's bounded file-inspection tools consistently across platforms.

## Defaults and UI

- Ordinary `git push` now reaches the serious-action approval flow; destructive force-push remains blocked. `--force-with-lease` retains its supported behavior.
- Bundled tool progress interval matches the 2-second runtime default.

## Performance and maintenance

- Retained the user-recorded controlled-run performance comparisons in the [1.0.10 changelog](../CHANGELOG.md#110---2026-11-01); these are local measurements, not portable timing guarantees.
- Offline behavioral coverage exercises cache request shape, prewarm retry, session fork isolation, and the packaged push defaults.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.10
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.10] entry.
