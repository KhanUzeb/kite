# Kite v1.0.11

**Date:** 2026-11-26

## Highlights

A reliability and hardening patch. Reasoning-only model turns fail over quickly instead of holding a stream open; stream cancellation and worker lifecycle transitions are bounded and race-safe; the GitHub "latest" release is selected by semantic version. Antigravity subscription turns keep the answer they already produced, and package scanning and directory listing do substantially less filesystem work. Secret redaction, untrusted-context wrappers, snapshot restore, and the display boundary where model-produced text reaches logs and screens are hardened as well.

## Streaming and model reliability

- Reasoning-only output is capped by the provider profile's `thinking_watchdog_chars`. Exceeding it raises `LongThinkingError` and retries once with reasoning disabled under a bounded 45 s fallback timeout instead of waiting for the full request deadline.
- Stream close runs on a daemon thread with a 50 ms join, so a stuck HTTP/SSE transport cannot delay cancellation or the fallback.
- The thinking-watchdog profile lookup is resolved once per stream rather than on every reasoning chunk, and the signed-in `agy` subscription turn no longer imports LiteLLM on a path that never uses it; the import is deferred to paths that need it.

## Antigravity subscription turns

- Text-only `agy` turns no longer receive the idle nudge that asks for tool calls or a submit. That nudge could make `agy` answer with an empty success payload, aborting the turn and hiding the answer already produced; the prose answer now goes through the normal submit gate instead. Independently reviewed against the real CLI reproduction, with the full suite at 482 passed / 3 skipped.
- The catalog default model is now `gemini-3.8-flash-medium`. Fallback IDs rejected by the real `agy --model` CLI, `gemini-3.7-flash-medium` and `gemini-3.1-pro-high`, were removed.
- OAuth model-list cache invalidation clears the canonical oauth key as well as the login alias, so clearing `grok` also drops the `xai`-keyed entry.

## Orchestrator and worker lifecycle

- Task and job status transitions are explicit, lock-protected, and terminal-once: tasks move `queued` → `running` → `revising` → `finished`/`failed`/`killed`, jobs `running` → `done`/`killed`/`failed`. Cancellation, timeout, and completion can no longer race into inconsistent state or emit duplicate terminal events.
- Scoped retries stay active: a retryable worker whose quality is `failed` or `partial` enters `revising`, remains visible as active in manager payloads, abort logic, and pruning, then returns to `running` before the retry.
- Structured handoff parsing, DuckDuckGo HTML result patterns, and env-var assignment checks use precompiled constants or plain string partition; episodic search pushes the filter into SQL and web-crawl deduplication reuses normalized keys.
- Package scanning shares one `iterdir` pass between marker detection and child enumeration and uses a deque for the breadth-first queue; directory listing uses a single `os.scandir` pass with cached `DirEntry` type information. Outputs are unchanged.

## Release and CI

- GitHub "latest" release selection now uses semantic version ordering instead of publish order (v1.0.8 was published seconds after v1.0.10).
- `uv.lock` is refreshed for the 1.0.11 project stamp with no dependency version upgrades; `uv lock --check` passes.
- `scripts/ci_check.ps1` contained two stray numbered `1.0.7` marker lines left by an old merge; they were removed so the script parses and its single release stamp is unambiguous.
- The `kite web_keys` argparse alias is now recognized as a CLI command, so `kite web_keys status` dispatches to the web-keys command instead of being misread as an implicit chat prompt.
- `/reasoning` is visible in slash completion again as a documented builtin; the `/effort` alias and legacy `/fast` shortcut stay hidden from the menu.

## Metrics

All figures below are local microbenchmarks on Windows / Python 3.12.14. The evidence scripts ran against baseline `e7d0eb9` and the working tree with identical inputs, and each figure was independently reproduced. These are neither provider response times nor end-to-end user-facing latency.

- **Compaction (synthetic microbenchmarks, interleaved A/B, identical outputs):** Windows / Python 3.12.14, baseline `e7d0eb9` vs working tree. Fact extraction on one 2,100,005-character user constraint message, 7 rounds: median 56.4 ms before vs 21.0 ms after in the evidence run; independent reproduction 81.4 ms vs 30.4 ms (2.67x). Full `compact_messages` path on 13 messages / 2,520,113 characters, 5 rounds: median 86.6 ms vs 53.7 ms; independent reproduction 93.8 ms vs 64.2 ms (1.46x). Synthetic text on one host; these are not end-user session latency or provider timings. Evidence: `%TEMP%/opencode/kite-watchdog-bench/bench_interleaved.py` and `bench_e2e.py`.
- **Antigravity import avoidance (microbenchmark, mocked turn):** `LitellmModel.query` with `run_agy_turn` stubbed, 3 fresh processes, median 11.06 s before vs <0.1 ms after. An independent single-process reproduction measured 8.995 s vs <0.001 s, with LiteLLM absent from `sys.modules` after the call. This measures import work only, **not** end-to-end response latency: the stub never invokes the `agy` CLI or a provider.
- **Filesystem hot paths (synthetic single-host microbenchmarks):** Windows 11 / Python 3.12.14, 7 samples per variant, pristine `HEAD` vs working tree, identical outputs. Package scan over 2,105 synthetic directories: median 2.6563 s before vs 1.3498 s after (independent reproduction 2.636 s vs 1.4278 s). Directory listing of 1,600 synthetic entries: median 0.2575 s before vs 0.0028 s after (independent reproduction 0.2747 s vs 0.0040 s). Limited to synthetic fixtures on one NTFS host; POSIX, real project layouts, cold sessions, and end-to-end task latency are unmeasured. Evidence: `%TEMP%/opencode/bench_release_metrics.py` and `release_metrics_fs.md`.
- **Cache and space metrics:** not measured; no figures are claimed.

## Security and UI hardening

- Redaction recognizes bare provider-prefixed credentials (`sk-proj-`, `sk-ant-`, `sk-or-v1`, `github_pat_`, `gsk_`, `AKIA…`, `AIza…`, `xapp-`) and `_PWD`-suffixed variables, without treating the shell's bare `PWD` as a secret.
- Tool-start cards, bash command blocks, and write/edit previews redact model-supplied arguments at the display boundary; approval views still show the exact command where a human must read it.
- Forged untrusted-context closing markers split across lines are neutralized; the bundled system prompt stops repeating the "do not repeat identical tool calls" line and points to the Setup message for execution context.
- Change-journal snapshots hash the whole file but retain at most the configured byte cap in memory. An oversized preimage is reported as a restore conflict instead of being silently truncated, which would destroy the rest of the file.
- Compaction fact extraction bounds normalization work on large tool output; `ls_search` counts only eligible hidden entries; the cached git dirty count is invalidated after checkpoint commits, undo, and pending restores.
- `EventKind` now declares the event kinds the loop and orchestrator actually emit (`limits`, `loop_hard_stop`, `provider_fault`, `provider_retry`, `submit_blocked`, `verification_status`, `orchestrator_start`, `orchestrator_end`), and behavioral tests cover these changes.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.11
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.11] entry.
