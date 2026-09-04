# Kite Universal Harness — Implementation Plan

**Date:** 2026-09-04  
**Status:** Largely implemented on `main` (see acceptance checklist). Remaining: full e2e replay harness, canonical event store in production UI.  
**Source:** `docs/superpowers/specs/2026-09-04-kite-e2e-reliability-design.md`

## Outcome

Make Kite universally capable within explicit capabilities: coding, terminal,
web, memory, installs, subagents, Windows/Linux, and chat. All capabilities
must use the same run, policy, approval, evidence, cancellation, and result
contracts.

Universal capability does not mean unrestricted autonomy. When a capability is
unsupported or disallowed, Kite must refuse clearly or request approval. It
must never silently widen scope, bypass guardrails, or claim success without
evidence.

## Non-negotiable invariants

1. `ApplicationRunService` is the only production entry point for CLI and REPL
   runs. The legacy `Harness` may remain its internal adapter during migration.
2. `PolicyEngine` is the single authorization authority. UI and agent-loop
   code must not maintain independent approval taxonomies.
3. Effects are derived from the complete tool call, including arguments, not
   only the tool name.
4. Exactly one terminal input owner is active: idle composer, busy composer,
   approval modal, or none during a transition.
5. Verification is artifact-aware. A passing command only verifies the paths
   and artifact kinds it actually covers.
6. Final claims are derived from journaled tool results and verification
   records, never from model prose alone.
7. Child agents inherit workspace, mode, approval, budgets, cancellation, and
   guardrail settings. A child cannot elevate any of them.
8. Repository instructions, skills, web results, and tool output are untrusted
   data. They cannot override user or system policy.
9. `--no-guardrails` remains visibly high-risk and never hides that fact.
10. The existing uncommitted `dashboard.html` change is preserved and is not
    mixed into core trains.

## Execution rules

- Land one train at a time. A train may use separate workers for tests and docs,
  but independent workers must not edit the same hot file concurrently.
- Each train is test-first: add a failing focused test, implement the smallest
  change, then run the focused tests and the full suite.
- Keep the application interfaces small and deep. Complexity belongs behind
  `ApplicationRunService`, `PolicyEngine`, the verification planner, and the
  approval coordinator rather than being repeated in CLI, REPL, or loop code.
- Preserve compatibility adapters until replay acceptance is green.
- Use fake providers only in tests and CI. Never add a live provider dependency
  to a unit test.

## Dependency order

```text
1 cache fix
  ↓
2 canonical effects + verification contracts
  ↓
3 ApplicationRunService entry-point cutover
  ↓
4 approval ownership + nested inheritance
  ↓
5 artifact verification + evidence-backed claims
  ↓
6 loop, platform, cancellation, and model capability hygiene
  ↓
7 replay acceptance, reducer completion, and dashboard states
```

The application entry-point cutover is intentionally early. Keeping it last
would allow later safety and verification work to land only on the legacy path.

## Train 1 — Cache completion crash

### Goal

Make successful completion and session persistence use the actual
`PromptCacheManager` interface.

### Implementation

- Inspect every completion-path cache read and replace any `.stats` access with
  the supported `session`/`summary()` data.
- Keep the persisted shape backward-compatible where practical.
- Ensure disabled prompt caching still produces a valid zero-valued summary.
- Include cache usage in the final run/session result without exposing provider
  secrets or raw provider payloads.

### Files

- `src/kite/models/cache.py`
- `src/kite/models/litellm_model.py` if adapter normalization is needed
- `src/kite/agent/runtime.py`
- `tests/test_cache.py`
- `tests/test_agent_completion.py`

### Gate

- A fake-provider run that completes successfully persists cache usage.
- A disabled-cache run completes without an attribute error.
- Existing cache parsing tests remain green.

## Train 2 — Canonical run, tool-effect, and verification contracts

### Goal

Create the small interfaces that all later trains consume, without changing
interactive behavior yet.

### Implementation

#### Tool effects

- Extend `SideEffect` with canonical effects:
  `workspace_read`, `workspace_write`, `destructive`, `network`,
  `durable_memory`, `package_or_skill_install`, `nested_agent`, and
  `long_running`.
- Keep a temporary compatibility mapping for existing serialized `read`,
  `process_control`, and `cost_bearing` values.
- Add argument-aware derivation from `ToolCall` to `ToolIntent`.
- Classify skill load versus skill install, memory list versus remember/forget,
  nested-agent creation, package installation, destructive shell operations,
  network commands, long-running jobs, and paths outside the workspace.
- Keep static tool metadata as scheduling hints only. `PolicyEngine.authorize`
  remains authoritative.

#### Verification

- Add `CheckSpec`, `VerificationPlan`, and `VerificationRecord` under
  `src/kite/application/verification/`.
- Add pure helpers that classify touched paths and select applicable checks.
- Model an empty required-check set explicitly; it means
  `changed_unverified`, not failure and not verified.
- Preserve a compatibility adapter so existing `VerificationCollector` callers
  can migrate incrementally.

#### Run contracts

- Extend `RunResult` only with fields needed by the canonical path: terminal
  verification status, evidence summary, approval/blocked reason, and changed
  paths. Avoid duplicating the full event journal in the result.
- Add canonical event payload shapes for `verification_plan`,
  `verification_record`, `approval_request`, `approval_decision`, and
  `submit_blocked`.

### Files

- `src/kite/application/tools/contracts.py`
- `src/kite/application/policy/engine.py`
- `src/kite/application/verification/__init__.py`
- `src/kite/application/verification/evidence.py`
- `src/kite/application/contracts.py`
- `src/kite/tools/metadata.py`
- New focused modules only where a contract cannot fit cleanly in the existing
  module.
- `tests/test_policy_execution.py`
- `tests/test_evidence_verifier.py`
- `tests/test_application_contracts.py`
- New `tests/test_tool_effects.py` and `tests/test_verification_plan.py`

### Gate

- The same `ToolCall` produces the same intent and policy decision in CLI,
  REPL, and fake-provider tests.
- Malicious repository text cannot change a policy decision.
- Unrelated passing commands do not satisfy a verification check.

## Train 3 — Early application entry-point cutover

### Goal

Make `ApplicationRunService.run(RunSpec, deps)` the only production route for
CLI and REPL execution while retaining `Harness` as an internal adapter.

### Implementation

- Move RunSpec construction to the CLI/REPL adapters; keep UI concerns out of
  the application module.
- Route `kite run`, follow-up runs, and interactive REPL turns through
  `ApplicationRunService`.
- Preserve the `LegacyEventBridge` while the inner harness still emits legacy
  events.
- Ensure the caller consumes `RunResult`, not an ad hoc legacy dictionary.
- Map approval denial, verification failure, cancellation, limits, and
  interruption to stable result statuses and CLI exit codes.
- Make event subscription cleanup exception-safe.

### Files

- `src/kite/application/service.py`
- `src/kite/application/adapters/harness.py`
- `src/kite/application/cli/result.py`
- `src/kite/cli/run.py`
- `src/kite/ui/repl.py`
- `src/kite/agent/runtime.py` only where adapter wiring is required
- `tests/test_application_contracts.py`
- `tests/test_cli_repl_services.py`
- `tests/test_cli_commands.py`

### Gate

- CLI and REPL each exercise the same fake-provider application path.
- No production CLI/REPL call site directly invokes `Harness.run`.
- Legacy JSONL/session compatibility remains green.

## Train 4 — Approval ownership and nested-agent inheritance

### Goal

Make approval reliable, single-owned, and effect-based.

### Implementation

- Add a small approval request/decision coordinator with unique request IDs,
  waiter lifecycle, EOF handling, cancellation, and disconnect handling.
- The worker publishes `approval_request` and waits; it never calls Rich
  `Prompt.ask` or another terminal reader.
- The UI pauses the busy composer before opening one modal and resumes it only
  after a decision.
- Render the reason and diff in exactly one place.
- Gate all mandatory effects, including network, durable memory, installs,
  nested agents, destructive operations, and out-of-workspace actions.
- Remembered approvals may short-circuit ordinary effects but never mandatory
  effects.
- Non-interactive required approval returns denial or the configured policy
  result immediately; it must never hang.
- Pass parent policy, mode, budgets, cancellation, workspace, and guardrail
  state into nested runs. Reject child attempts to change them.

### Files

- `src/kite/application/policy/engine.py`
- New `src/kite/application/policy/approval.py` if needed for request/decision
  contracts
- `src/kite/ui/approval.py`
- `src/kite/ui/repl.py`
- `src/kite/ui/render.py`
- `src/kite/agent/loop.py`
- Nested-run creation code under `src/kite/agent/` and `src/kite/tools/`
- `tests/test_approval.py`
- `tests/test_mandatory_approval.py`
- `tests/test_orchestrator.py`
- New `tests/test_approval_ownership.py` and
  `tests/test_nested_policy_inheritance.py`

### Gate

- Keyboard approval works while the busy composer is active.
- EOF and Ctrl+C stop safely.
- Exactly one approval panel and one reason are rendered per request ID.
- A child cannot turn on yolo behavior, disable guardrails, or gain a broader
  workspace.

## Train 5 — Artifact-aware verification and truthful claims

### Goal

Replace the global “edited means pytest” rule with a plan-driven evidence gate.

### Implementation

- Build a `VerificationPlan` after edits and update it as touched paths change.
- Select checks by artifact kind:
  - Python: targeted pytest when related tests exist, otherwise touched-path
    lint/syntax checks.
  - HTML: in-process parse/structural checks; never pytest solely because HTML
    changed.
  - JS/TS: configured project check or `node --check` fallback.
  - CSS/config/docs: applicable parser, structural, or configured lint checks.
  - Unknown files: no invented required check; report
    `changed_unverified` honestly.
- Associate every verification record with affected paths and the check that it
  satisfies.
- Prevent an unrelated green command from satisfying another artifact kind.
- Replace generic test nudges with plan-specific nudges.
- Add an evidence ledger linking final claims to tool results and records.
- Reject unsupported claims such as “fixed”, “complete”, “tests pass”, or
  “build succeeds” when the matching evidence is absent.
- Allow submission with edits and no required checks, but label it
  `changed_unverified`.
- Keep casual chat outside the build verification gate.

### Files

- `src/kite/agent/verification.py`
- `src/kite/agent/loop.py`
- `src/kite/application/verification/evidence.py`
- `src/kite/application/verification/`
- `src/kite/application/events.py`
- `tests/test_verification.py`
- `tests/test_submit_gate.py`
- `tests/test_evidence_verifier.py`
- New artifact-selection and claim-ledger tests

### Gate

- HTML-only edits never invoke or require pytest.
- Python and mixed edits select only relevant checks.
- Failed checks remain failed even if an unrelated command passes.
- The final result separates changed, verified, unverified, blocked, and
  out-of-scope work.

## Train 6 — Loop, platform, cancellation, and model hygiene

### Goal

Make the agent robust across supported platforms and model capability levels.

### Implementation

- Add a structured `submit` action. Accept
  `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` only as a compatibility path for old
  sessions.
- Hide raw reasoning and recovery dialogue by default; expose concise progress
  events instead.
- Limit build-mode no-tool recovery to one attempt, then ask for clarification
  or report a blocker. Keep casual chat literal.
- Detect Windows/POSIX shell capabilities and give platform-appropriate
  guidance. Prefer PowerShell, `rg`, and Kite tools on Windows.
- Add process-tree cancellation and bounded retries for long-running work.
- Add model capability metadata for chat, tool calling, context size, vision,
  and reasoning. Filter or visibly warn on unsuitable agent models while
  preserving manual selection.

### Files

- `src/kite/agent/loop.py`
- `src/kite/agent/runtime.py`
- `src/kite/data/prompts/system.md`
- `src/kite/data/prompts/mode_build.md` and related prompt files
- `src/kite/guardrails/bash.py` and existing command-policy modules
- `src/kite/tools/jobs.py`
- `src/kite/providers/`
- `tests/test_agent_completion.py`
- `tests/test_prompts.py`
- `tests/test_inspection_bash.py`
- `tests/test_cancellation_parallel.py`
- `tests/test_provider_retry.py`
- New platform and model-capability tests

### Gate

- Windows and POSIX replay fixtures produce platform-appropriate commands.
- Cancellation terminates child processes and returns a stable cancelled
  result.
- A non-tool-calling model is either rejected for agent mode or clearly warned.
- No raw reasoning or four-turn idle recovery loop reaches the user transcript.

## Train 7 — Replay acceptance and dashboard completion

### Goal

Prove the complete behavior from the supplied transcript, then add dashboard
states without changing core verification semantics.

### Implementation

- Persist/load the canonical event sequence needed for deterministic replay.
- Ensure the reducer projects events for REPL and dashboard without becoming an
  authority or a second input reader.
- Replay the supplied failure transcript and assert no duplicate prompt, leaked
  reasoning, unnecessary pytest, false completion, or unapproved side effect.
- Only after replay passes, make additive dashboard changes for loading,
  network failure, rate limiting, stale data, and empty states.
- Keep browser smoke/manual dashboard verification separate from the Python
  verification plan.

### Files

- `src/kite/eval/`
- `src/kite/application/events.py`
- `src/kite/application/ui/reducer.py`
- `src/kite/dashboard/` or existing dashboard adapter files, if present
- `dashboard.html` — additive states only; preserve the user’s existing diff
- `tests/test_replay.py`
- `tests/test_dashboard.py`
- New transcript acceptance tests

### Gate

- The original transcript replays deterministically.
- CLI, REPL, and reducer agree on status and evidence.
- Dashboard changes do not alter policy, verification, or run execution.

## Cross-cutting test matrix

Every train keeps fake-provider coverage for:

- Linux and Windows, Python 3.11 and 3.12 in CI.
- Interactive and non-interactive execution.
- Restricted mode, supervised approval, automatic low-risk edits, and visible
  `--no-guardrails` behavior.
- Hostile repository instructions attempting to widen permissions.
- Cache persistence after success.
- HTML-only, Python-only, mixed, config, docs, and unknown artifacts.
- Failed, unrelated, and passing verification commands.
- Approval keyboard flow, optional mouse flow, EOF, Ctrl+C, and disconnect.
- Network, memory mutation, skill/package install, destructive actions,
  long-running jobs, and nested-agent approvals.
- Child policy inheritance and cancellation.
- Model lists containing stale and non-agent-compatible entries.
- Replay of the supplied transcript.

## Documentation updates

Update only when behavior changes are landed:

- `kite_commands.md` for CLI/REPL behavior and exit statuses.
- `docs/cli-ux.md` for composer, approval, modal, and status behavior.
- `CONTEXT.md` for new domain terms such as effects, verification plan, and
  evidence ledger.
- `src/kite/data/prompts/` for submit, platform, and evidence instructions.

## Final acceptance checklist

- [x] Completion no longer accesses nonexistent cache statistics.
- [x] All production CLI/REPL runs enter through `ApplicationRunService`.
- [x] Tool effects are argument-aware; `PolicyEngine` authorizes in production loop via `ToolExecutor`.
- [x] Mandatory effects cannot be bypassed by remembered approval or yolo mode.
- [x] Nested agents cannot elevate policy, scope, or guardrails.
- [x] Only one terminal input owner exists at any time (busy composer approval polling).
- [x] HTML edits do not require pytest (artifact-aware plans).
- [x] Final claims cannot outrun recorded evidence (submit gate + `submit_blocked`).
- [x] Structured `submit` tool registered; legacy bash marker retained.
- [x] ReplayBundle supports events + acceptance criteria.
- [ ] Cancellation, retry, and platform guidance fully verified on Windows and POSIX.
- [ ] Model capability mismatches are handled visibly everywhere.
- [ ] The supplied transcript replays without the observed failures (full e2e replay harness).
- [x] Dashboard states are additive and do not block core harness correctness.
- [x] Full test suite is green in the supported CI matrix.

## Explicit non-goals

- No in-process Bash virtual machine.
- No new full-screen TUI framework.
- No omp² convars, Director stack, or XML session DOM.
- No live provider calls in unit or CI tests.
- No dashboard checks inside the core Python verification gate.
- No destructive rewrite of the existing `dashboard.html` work.
