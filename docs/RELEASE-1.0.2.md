# Kite v1.0.2

**Date:** 2026-09-25

## Highlights

- **Token Efficiency & Harness Pass** — Comprehensive Eric Zakariasson token efficiency pass covering telemetry, prompt split, spill management, tiering, error handling, history compaction, and routing.
- **Antigravity & Auth Caching** — Enhanced verification via the official `agy` flow and cached OAuth status probes with hermetic test isolation.
- **Startup Performance** — Background prewarming of LiteLLM imports and inlined CLI parser structure for lightning-fast startup.
- **Robust Self-Update & Windows Handoff** — Detached background handoffs, shim-aware helpers, install lock retries, and clean uninstall flows for Windows.
- **Crew & Multi-Agent Orchestration** — Crew coalescing, whole-tree cost aggregation, and richer worker context for orchestrated agents.
- **NVIDIA & Provider Resiliency** — Gated parallel tools on explicit support for NVIDIA, stream fallback, gateway key loading, instruction preservation, and cross-platform CRLF normalization.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.2
```

Windows: `.\scripts\install.ps1`. Global CLI: `uv tool upgrade kite`.

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.2] entry.
