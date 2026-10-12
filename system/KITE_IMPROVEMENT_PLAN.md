# Kite Improvement Roadmap

## Context

Kite already has separate agent, model/provider, REPL, security, context, memory, tool, and subagent systems, so improvements should land as small behavior-focused PRs rather than a broad refactor. This roadmap covers security, UI/UX, backend/performance, context/memory, the agent loop, model connections and weak errors (including `agy` linking), `/quit` and `/exit` hangs, subagents, and tools. The repository currently has no top-level `system/` directory; this file is the agent-facing roadmap. Implement each numbered item as a separate PR in order.

## PR sequence

### PR 1 — Store the roadmap for coding agents

This file is the roadmap. No production behavior changes in this PR.

### PR 2 — Reproduce and fix REPL shutdown hangs

Preserve existing idle EOF and `/quit` behavior in `ChatSession.run()` and add end-to-end coverage for `/q` and `/exit`, busy-turn quit/EOF, and exit with active bash and subagent jobs. Use a subprocess/PTY scenario and a strict timeout to prove terminal control returns and no owned child process remains. Inspect `ChatSession._run_task()`, its busy-composer callbacks, `_teardown_jobs()`, and `JobRegistry.kill_all()` / `_kill_job()`; fix only the hang or leaked-process path demonstrated by the regression, retaining bounded cleanup and terminal restoration. Do not state the code definitively hangs: current tests prove idle EOF and `/quit` return, but do not exercise busy shutdown through process termination.

**Execution evidence:** Existing REPL tests cover idle EOF and `/quit`. `scripts/e2e_smoke.py` reports that PTY checks need POSIX and offers `--headless-only`; the hang was not reproduced on Windows, and headless mode cannot verify terminal restoration. No shutdown behavior was changed. Keep busy interactive exit/job teardown PTY coverage as a follow-up.

### PR 3 — Classify retryable `agy` failures explicitly

Trace `AntigravityExecError` from `parse_agy_payload` through `LitellmModel._query_agy()` to `is_transient_provider_error()` and `DefaultAgent.query()`. Distinguish retryable network/service/429/5xx errors from authentication, quota, malformed-payload, and other permanent errors; route only retryable conditions through the existing bounded backoff, without nested LiteLLM retries. Add deterministic tests proving transient `agy` failure retries then succeeds and permanent failures do not retry.

**Execution evidence:** Added `AntigravityTransientError`; auth/quota/malformed responses remain permanent, while network/service/429/5xx errors use the existing bounded retry. `tests/test_agent.py`, Antigravity OAuth, and model tests pass.

### PR 4 — Make existing model/auth errors actionable

Follow errors from `providers/resolve.py`, provider auth status/login (especially Antigravity `agy` linking), and model calls through their current CLI/REPL renderers. Improve those existing messages to identify whether the failure is missing/unverified auth, connection timeout, rate limit, or upstream service failure and give the corresponding next action. Preserve exception cause for diagnostics, redact credentials and sensitive response content, and do not add a new command or retry layer. Add focused tests for each rendered category, secret redaction, failed/successful `agy` verification, and provider failure propagation. There is no evidence yet that every category is currently misreported; alter only paths whose present output is unclear or unsafe.

**Execution evidence:** Added typed error categories, next-step guidance, and credential redaction to CLI/REPL rendering. Antigravity session probes now report sanitized timeout, command failure, or no-model details and do not mark failed verification as linked. Provider, OAuth, agent, and CLI tests pass.

### PR 5 — Verify context and memory trust/budget boundaries

Audit the complete context assembly path in `application/context.py`, `context/discovery.py`, `memory/store.py`, and `agent/runtime.py`; establish source trust labels, ordering, truncation, and inclusion decisions. Fix demonstrated cases where repository/tool/memory content is elevated to trusted instructions, required user/project context is silently lost under budget, or prompt accounting exceeds the selected model's input capacity. Reuse `ContextItem`, `ContextBudget`, trust labels, and snapshot inspection. Add behavior tests for adversarial repository/memory text, competing source budgets, and oversized inputs, asserting the final rendered prompt and inclusion/omission decisions. Preserve memory storage and forget semantics.

**Execution evidence:** Prompt-bound memory and automatically gathered repository metadata were directly injected as trusted text; user/project instruction files remain trusted, while memory and repository-data sections now use escaped untrusted markers. Competing model-token budgets and the standalone `ContextAssembler` are not on the current live assembly path, so no speculative accounting rewrite was made. Memory/project-init/performance-hardening tests pass.

### PR 6 — Close confirmed security boundary gaps

Review external-input boundaries in `guardrails/sandbox.py`, `guardrails/ssrf.py`, `guardrails/redact.py`, `application/policy.py`, `application/execution.py`, `tools/jobs.py`, and plugin loading. Follow existing path authorization, DNS/IP validation, approval, child-environment filtering, and redaction mechanisms; fix only reachable bypasses or secret exposure demonstrated by tests. Never weaken sandbox or approval behavior. Approved `git push` must remain user-approvable in restricted mode; force-push remains hard-blocked. Add a regression for each confirmed boundary failure; if an inspected boundary already meets its contract, leave it unchanged and record evidence in the PR description rather than adding speculative code.

**Execution evidence:** SSRF peer validation previously used proxy-configured connections, so it validated the proxy peer rather than the destination; the safe opener now disables environment-configured proxies and a regression failed before the fix. Restricted-mode `git push` now reaches the existing network authorization/approval policy; an allow decision executes the command while force-push remains hard-blocked. Focused security, web, policy, and approval tests pass. Reviewed sandbox, redaction, plugin loading, jobs, and secret handling; no additional confirmed bypass found.

### PR 7 — Enforce subagent write scope before execution

Pass each declared `task.scope` from `agent/orchestrator.py` into the worker's tool authorization/execution boundary in `agent/runtime.py`; reject out-of-scope mutations before they run, using normalized paths and the existing sandbox/policy mechanisms. Keep post-run touched-path checks only as a quality signal, not containment. Add tests proving an attempted out-of-scope write has no filesystem side effect and an in-scope write remains allowed. Current `gate_result()` compares reported touched paths after the worker run, while the worker tool allowlist restricts tool names rather than paths; that does not prove out-of-scope writes are prevented.

**Execution evidence:** `write_scope` now flows through `SubagentOrchestrator` → worker `HarnessConfig` → `RuntimeOptions` → `PolicyEngine`. Scoped workers cannot mutate paths outside the normalized scope, even with `no_guardrails` or approval; scoped bash mutations are denied because shell destinations cannot be reliably bounded. Tests exercise a real `ToolExecutor` boundary and filesystem side effects; in-scope writes remain allowed. Empty scope denies all writes. Focused application/orchestrator tests pass.

### PR 8 — Fix demonstrated agent-loop and tool-result failures

Trace model response → tool dispatch → normalized result → next query across `agent/loop.py`, `application/execution.py`, `application/tools.py`, and `tools/coding.py`. Add regressions for any evidenced consumer-visible failure in malformed/partial tool calls, interrupted execution, or provider recovery, then fix the narrowest owning layer. Keep the current retry policy and verification/submit gate; do not add tool retries or bypass approval. Tests must assert conversation/side effects and state transitions, not only return shapes. Existing loop/executor systems are substantial; do not refactor them without a failing behavior to justify it.

**Execution evidence:** Existing tests cover malformed tool argument repair, response/tool-call pairing after interruption and submit, parallel result ordering, provider retry classification, and tool failure state. `tests/test_agent.py` passes; this audit found no new loop/tool defect warranting speculative edits.

### PR 9 — Measure backend performance and improve a concrete UX defect

Use existing benchmark/test infrastructure (`scripts/profile_cli.py`, `kite bench`, `tests/test_bench.py`) to measure startup, prompt/context assembly, and repeated tool/model-loop overhead before changing code. Optimize only a measured regression or avoidable repeated work in existing paths; retain output and model request semantics and include before/after measurements. Separately, inspect `ui/repl.py`, `ui/complete.py`, and `ui/render.py` for a concrete keyboard/composer/render accessibility or discoverability defect. Fix only a confirmed defect with interaction-level coverage or a PTY smoke; do not redesign the UI or add speculative caching.

**Execution evidence:** Windows `kite bench --suite full` baseline: `cli_import` 163.7 ms, `cold_cli_help` 411.2 ms, `context_gather` 23.7 ms, `agent_loop_50` 132.4 ms, `agent_loop_200` 507.4 ms, and `session_append_500` 3732.3 ms; no before/after evidence identified a safe optimization. Busy `/quit` hang was not reproduced on Windows. The repository PTY smoke is POSIX-only; `--headless-only` cannot verify terminal restoration. Keep that cross-platform PTY test as a follow-up; do not claim the hang is fixed.

## Critical files & anchors

- `src/kite/ui/repl.py` — `_handle_slash()`, `_run_task()`, `_teardown_jobs()`, and `run()` define idle/busy shutdown and worker waiting.
- `src/kite/tools/jobs.py` — `kill_all()` and `_kill_job()` define process/subagent teardown.
- `src/kite/models/retry.py` — `is_transient_provider_error()` and `retry_delay_s()` are the shared retry policy.
- `src/kite/providers/auth/antigravity_exec.py` and `src/kite/models/litellm_model.py` — `agy` error production and model adapter path; inspect afresh before editing.
- `src/kite/application/context.py` and `src/kite/memory/store.py` — trust labels, budgets, prompt inspection, and memory retrieval.
- `src/kite/agent/orchestrator.py`, `src/kite/agent/runtime.py`, and `src/kite/application/policy.py` — worker write-scope propagation and pre-execution enforcement.

## Verification

- Run focused tests for each behavior PR and `pytest -q` once the final production changes are integrated.
- PR 2: run the actual interactive REPL under `scripts/e2e_smoke.py` (or an equivalent repository PTY harness) with idle `/exit`, busy `/quit`, and active background work. Each scenario must exit before its timeout, restore terminal state, and leave no child/job running. Existing smoke covers `/help` → `/quit` only; add deterministic automated regression coverage for busy shutdown.
- PR 3–4: use fake `agy`/provider adapters and injected errors; verify transient retry succeeds within configured attempts, permanent auth/quota/parse errors fail once, rendered guidance names the next action, failed `agy` login does not mark the account linked, and credential strings never appear.
- PR 5–8: add focused tests in matching context, guardrail, subagent, loop/tool, and jobs modules. Use adversarial, oversized, and failing inputs where relevant; assert externally visible result, state transition, or side-effect boundary.
- PR 9: baseline measured on Windows; no confirmed safe optimization or UX defect found. The interactive PTY shutdown test remains a POSIX follow-up.

**Test-count audit:** Reviewed the touched security, agent, provider, memory, and subagent suites. No clear duplicate or superseded tests were identified, so no tests were deleted solely to lower the count; retain consumer-visible behavioral coverage rather than an artificial collection target.

**Final verification:** `uv run --no-sync pytest -q` — 457 passed, 3 skipped (Windows-specific POSIX limitations); focused provider/security/policy/orchestrator checks passed after final imports/lint fixes. `ruff check` passes on changed Python files.

**Documentation:** `kite_commands.md` covers worker scopes, approval-gated `git push`, and model/`agy` errors; `SECURITY.md` covers untrusted repository data, scope enforcement, direct SSRF connections, and network policy.

## Assumptions & contingencies

- The requested "system directory" means a repository-root `system/` directory for agent-facing planning material. No such directory existed in the root listing, so PR 1 creates it; do not place the roadmap under `src/kite/data/prompts/`, which contains the runtime system prompt.
- Use separate PRs in the listed order. PRs 2–9 depend only on PR 1's roadmap. If a candidate audit in PRs 4–6 or 8–9 finds no observable defect, record the evidence and omit speculative code rather than inventing a problem. If the PR 2 PTY scenario is unreliable on a supported platform, retain platform-neutral deterministic lifecycle coverage and run PTY smoke where supported; do not omit busy-shutdown coverage.
