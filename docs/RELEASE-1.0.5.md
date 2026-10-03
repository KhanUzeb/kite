# Kite v1.0.5

**Date:** 2026-10-03

Reliability release: kills the infinite-thinking hang, makes long tasks
visible and resumable, tightens the submit gate against hallucinated
"done", and cleans up answer streaming.

## Hang fix

- Provider establishment is now bounded and cancel-responsive
  (`_bounded_completion_call`): a held-open connection raises `TimeoutError`
  past the model timeout (default 180s) and surfaces as a retryable
  `ProviderFault` instead of spinning forever. Esc interrupts promptly.
- Loop-level watchdog: per-attempt hard bound (2× model timeout + 60s)
  with interrupt polling, so no model can hang the worker thread.
- `agent_end` always fires (hardened `finally`), and the REPL turn loop
  resets busy/running/spinner state in `try/finally` — no more stuck
  "working" footer after Ctrl-C or save failures.
- Long-reasoning streams emit `stream_thinking_long` ("thinking N chars")
  instead of looking frozen; coalescer flushes on `turn_end`;
  `interrupt`/`error` clear stale running labels.

## Answer text

- No split-style flicker on streamed `## `/`- ` lines; fenced code blocks
  cap streamed output at 4k chars with an explicit truncation pointer.
- Tool output capped centrally (12k, head+tail) with `...[truncated]`
  markers and spill-file pointers; tables truncate with `…`, never silent
  slices.
- Prompts require `path:line`/command citations and proper `submit`-tool
  finishes; casual chat stays literal (no checklist for `hi`).

## Long tasks

- Headless display renders progress heartbeats, checkpoints, compaction,
  context ratio, retries/faults, approval gates, and job elapsed times —
  long runs never look hung.
- Every non-success exit logs a mission/done/next/todos continuity brief
  plus `kite resume <sid> "continue from checkpoint"`; `tasks run` prints
  row errors with resume hints.
- Phantom `"running"` jobs eliminated (failed drain marks `job_end`);
  two new bench cases cover the exit path.

## Hallucination gate

- Submit requires `## Done` + `## Changed` (+ `## Verification` with `✓`
  when checks exist) for edited sessions; unrelated passing tests no
  longer satisfy evidence; `py_compile` / `node --check` count as checks.
- Relaxed path (`verify_before_submit=False`) and no-edit turns keep prior
  behavior — casual finishes still submit.

## Connection health (verified, no change)

- Boot stays off-network (fast probe, lazy resolve); misconfigured
  providers fail fast with `kite keys` / `kite login` hints; transient
  faults retry with countdown, auth fails hard, sessions survive for
  `resume --retry`. Known gaps logged for next pass: Codex probe without
  timeout, generic 429 `Retry-After` unparsed, one fault rendering 3×.

## Tests

114 collected (113 passed, 1 platform skip) — unchanged count, still
under the 150 CI budget.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.5
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.5] entry.
