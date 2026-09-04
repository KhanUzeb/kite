# Kite End-to-End Reliability, Safety, and UI — Design Spec

**Date:** 2026-09-04  
**Status:** Approved (design dialogue)  
**Delivery:** Spec-first, then parallel subagents per train (approach 3)  
**External reference:** [Stencil Harness Playbook](https://stencil.so/blog/harness-playbook)  
**Preserved work:** Uncommitted `dashboard.html` must not be reverted

---

## 1. Purpose

Ship the next-release priority: core agent safety, truthfulness, verification, and terminal interaction; then complete the 0.9→1.0 application-layer cutover. Confirmed failures from transcript/screenshot include:

- Session completion crash (`PromptCacheManager.stats` does not exist)
- HTML-only edits incorrectly forcing pytest
- Leaked internal reasoning / recovery dialogue loops
- Inconsistent gating for approval, memory, skill install, network, subagents
- Nested agents with automatic approval elevation
- Unix-only command guidance on Windows
- Capability-unaware model selection
- Final answers claiming completion without evidence
- Dual terminal readers (`Prompt.ask` vs busy follow-up composer)
- Text-only approval UI, duplicated approval reasons
- `ApplicationRunService` not yet the single production execution path

---

## 2. Design envelope (playbook)

Apply these harness constraints without rebuilding omp² (no convar system, no in-process Bash VM, no XML session DOM, no Director stack rewrite):

| Playbook rule | Kite form |
|---|---|
| One authoritative session; state from the journal | `EventEnvelope` + reducer UI; approval, verification, tool results, and final report are journaled events |
| Trusted control plane; sandbox only executes | Host `PolicyEngine` + tool-effect authorization; tools receive bounded requests |
| Bounded, cancellable work | Jobs/subagents share process-tree cancel, budgets, parent policy; children cannot elevate |
| Explicit model/provider compatibility | Capability metadata; filter/warn non-agent models |
| Views are projections | REPL/dashboard/renderer fold the same events; **exactly one terminal input owner** |

Architecture tests that must remain true:

- Interactive local REPL
- Non-interactive `kite run`
- Hostile-repo path: repository instructions never override user/system policy
- Future spectator/remote: possible because UI is a projection, not an authority

Graduated autonomy remains the default: low-risk workspace edits may proceed automatically; installations, durable memory, subagents, external/network actions, and destructive operations always require confirmation. `--no-guardrails` stays a visibly marked high-risk override.

---

## 3. Delivery model

### 3.1 Nine trains + dashboard

| # | Train | Primary owners |
|---|---|---|
| 1 | Cache persistence crash + completed-run regression | `models/cache.py`, `agent/runtime.py` |
| 2 | Artifact-aware `VerificationPlan` / `VerificationRecord` | `agent/verification.py`, `application/verification/` |
| 3 | Approval terminal ownership + interactive modal | `ui/approval.py`, `ui/repl.py`, `ui/render.py` |
| 4 | Tool effects + mandatory gates + nested inherit | `tools/metadata.py`, `application/policy/`, `ui/approval.py` |
| 5 | Task contract + evidence ledger + claim rejection | `agent/loop.py`, prompts, application contracts |
| 6 | Hide reasoning / structured submit / recover-once | `agent/loop.py`, prompts, render |
| 7 | Windows/platform command guidance + cancel/retry | prompts, bash policy, jobs |
| 8 | Model capability metadata + filter/warn | `providers/`, catalog |
| 9 | `ApplicationRunService` production path + replay UI | `application/`, CLI/REPL adapters |
| — | P2 Dashboard | existing `dashboard.html` + loading/error states |

### 3.2 Parallel waves (option 3)

| Wave | Parallel trains | Gate |
|---|---|---|
| A | 1 · 2 · 8 (light) | green fake-provider tests |
| B | 3 | interactive approval tests |
| C | 4 | permission/nested tests |
| D | 5 | claim-rejection tests |
| E | 6 · 7 | loop + platform tests |
| F | 9 | full replay acceptance |
| G | Dashboard P2 | manual/browser note |

Hot-file serialization: one writer at a time for `agent/loop.py`, `ui/approval.py`, `ui/repl.py` within a wave.

Umbrella spec → per-train implementation plans under `docs/superpowers/plans/` → subagent per train with review gates.

---

## 4. Tool effects and policy

Approve at the **capability boundary**, not by treating opaque bash strings as the sole approval unit. Host policy decides; execution only runs what was authorized. Nested agents inherit — they never receive a second, looser settings surface.

### 4.1 Effect taxonomy

Replace binary read-only/mutating as the authorization truth. Extend `SideEffect` in `application/tools/contracts.py` and derive effects **per call** (arguments matter):

| Effect | Examples | Default gate |
|---|---|---|
| `workspace_read` | `read`, `grep`, `glob`, `ls`, `memory list`, `skill` load (no install) | Auto in build/auto; plan OK |
| `workspace_write` | `write`/`edit` inside workspace; low-risk in-workspace redirects | Graduated: auto may allow; supervised asks |
| `destructive` | `rm`, git history rewrite, force checkout, wipe | Always confirm (no yolo/remember bypass) |
| `network` | web tools, curl/iwr, context7 | Always confirm |
| `durable_memory` | `memory remember` / `forget` | Always confirm |
| `package_or_skill_install` | pip/npm/…, `skill install=…` | Always confirm; split from skill load |
| `nested_agent` | `subagent` / `task` | Always confirm; child inherits parent |
| `long_running` | background jobs, long bash | Confirm or budget + cancel handle |

`todo_write` remains session-local (not durable memory). Plan mode denies every write-capable or side-effectful action, including bash that writes indirectly (inspection-only bash retained).

### 4.2 Derivation rules (fixes known gaps)

- `skill`: load → `workspace_read`; `install` present → `package_or_skill_install`
- `memory`: `list` → read; `remember`/`forget` → `durable_memory` (today metadata incorrectly marks all memory read-only)
- `subagent`/`task`: → `nested_agent` (+ cost); not read-only
- `bash`: classify via existing parsers plus Windows equivalents; approve **effects**; show short capability reason
- Outside-workspace path → external/destructive-class; always confirm or deny per mode

### 4.3 Authority stack (hostile repo)

1. User flags + `ApprovalMode` + `--no-guardrails` (UI still marks high-risk)
2. System / Kite policy
3. Project `AGENTS.md` / skills / web / tool output — **untrusted data only**; cannot widen permissions

### 4.4 Nested agents

- Spawn requires `nested_agent` approval
- Child seeds: workspace, approval mode, budgets, cancel token, `no_guardrails`, plan/build mode from parent
- Child cannot escalate approval or disable guardrails
- Child tool calls use the same `PolicyEngine`; parent UI owns interactive approvals

### 4.5 Wiring

- Single authorizer: expand `PolicyEngine.authorize` + arg-aware `side_effects_for(call)`
- Legacy `ui/approval.py` becomes a thin adapter until train 9
- `tools/metadata.py` gains effect hints for scheduling; gate truth lives in policy contracts
- Out of scope for this program: in-process Bash VM

---

## 5. Verification and evidence

Verification is part of the interface: a machine-readable definition of success the agent cannot redefine with an unrelated green command.

### 5.1 Problem today

`VerificationCollector` treats “any edit → need a pytest-shaped passing command.” HTML-only edits get nudged/blocked toward pytest. Application `EvidenceVerifier` exists but is not the production gate.

### 5.2 Types

```text
VerificationPlan
  touched_paths: list[str]
  artifact_kinds: set[html|python|js|css|config|docs|other]
  required_checks: list[CheckSpec]   # may be empty → allow "changed, not verified"
  optional_checks: list[CheckSpec]

CheckSpec
  kind: parser | project_test | lint | syntax | structural
  command: str | None          # None = in-process check
  affected_paths: list[str]
  platform: windows | posix | any

VerificationRecord
  check: CheckSpec
  command: str
  affected_paths: list[str]
  exit_status: int | None
  ok: bool
  output_summary: str
  satisfies: list[str]
```

### 5.3 Plan selection

| Touched kinds | Checks |
|---|---|
| Python | Targeted pytest if related tests exist; else ruff on touched paths; never whole-suite unless asked |
| HTML | In-process parse / structural checks — never pytest |
| JS/TS | Project script if present, else `node --check` |
| CSS | Parser or project lint if configured |
| Config | Parse round-trip |
| Docs | Optional link/frontmatter; never pytest |
| Mixed | Union of applicable checks; each record tagged to paths |
| Unknown / non-code | Empty required set → honest **changed, not verified** |

Never: “something edited ⇒ run pytest.” Never: unrelated passing command satisfies a different artifact kind.

### 5.4 Evidence ledger and claims

- Ledger links final claims → tool results + `VerificationRecord`s
- Reject unsupported “fixed / passed / complete / tests pass” without matching records
- Terminal statuses: `verified` | `partial` | `changed_unverified` | `failed` | `blocked` | `idle`
- Final summary must separate: changed / verified / unverified / blocked / out-of-scope
- Edits + empty required checks → submit allowed with `changed_unverified`

### 5.5 Task contract

Per run, journal:

- user objective
- allowed workspace
- prohibited actions
- expected deliverables
- unresolved questions

Repo files, skills, web, tool/command output = untrusted data. User/system policy wins. Require inspect-before-edit (soft nudge, then harden).

### 5.6 Wiring

- Unify loop collector with `application/verification` as canonical event types
- Nudges cite the plan’s checks, not a generic pytest string
- Events: `verification_plan`, `verification_record`, `submit_blocked`
- Dashboard browser smoke stays out of core Python verification

---

## 6. Terminal input and approval modal

Views are projections; the UI must not become a second stdin authority.

### 6.1 Invariant

Exactly one component may read terminal input at a time:

| Owner | When |
|---|---|
| Idle composer | No turn running |
| Busy follow-up composer | Turn running, no pending approval |
| Approval modal | `approval_request` outstanding |
| (none) | Mid-transition; EOF/Ctrl+C resolving |

### 6.2 Protocol

```text
Worker                          UI (main / prompt_toolkit loop)
  |-- emit approval_request ----→|  pause busy composer
  |   {id, tool, effects,        |  show ONE interactive modal
  |    reason, diff, mandatory}  |  (reason rendered here only)
  |   wait on Future/Event <-----|  user chooses a/s/p/n/q
  |←-- approval_decision --------|  resume composer (or stop)
```

Rules:

1. Worker-thread approver never calls `Prompt.ask` / Rich Prompt
2. Publishes `approval_request` with unique `request_id`; blocks on UI-filled waiter
3. `RunDisplay._on_approval` does not print the reason panel (modal owns it)
4. Gate on policy effects, not only `MUTATING_TOOLS`

### 6.3 Modal UX

- Interactive prompt_toolkit dialog / focused keybinding layer
- Keys: `a` allow · `s` session · `p` always (hidden if mandatory) · `n` deny · `q` stop; arrows/tab/Enter; mouse when supported
- If mouse unavailable: clear keyboard instructions
- Focus indicator: `approval` vs `follow-up`
- EOF / Ctrl+C / disconnect → `stop`
- One panel per `request_id`

### 6.4 Non-interactive

- No TTY: required approval → `deny` (or configured policy); never hang
- Remembered patterns short-circuit before emitting a request (except mandatory effects)

---

## 7. Loop hygiene, platform, models, cutover, dashboard

### 7.1 Internal dialogue (train 6)

- Hide raw `stream_reasoning` by default; show concise progress statuses
- Keep recovery/idle nudges out of visible conversation history
- Replace `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` with structured `submit` action; marker only for old sessions
- After one no-tool recovery in build mode: clarify or report blocker — no four-turn idle loop
- Casual chat (`hi`, …) stays outside build recovery

### 7.2 Platform (train 7)

- Detect Windows vs POSIX; expose shell capabilities to the model
- Stop recommending Unix-only peek commands on Windows; prefer PowerShell + `rg` + kite tools
- Platform-aware command validation; process-tree cancel; bounded retry
- Win + Linux replay tests
- Out of scope: in-process Bash VM

### 7.3 Model capabilities (train 8)

- Metadata: chat, tool calling, context size, vision, reasoning
- Default/agent path prefers tool-calling models; unsuitable models filtered or visibly warned
- Manual selection remains available
- Tests: broad fake lists + stale catalog entries

### 7.4 ApplicationRunService production path (train 9)

```text
CLI / REPL
  → ApplicationRunService.run(RunSpec, deps)
      → PolicyEngine + VerificationPlan + BudgetLedger + cancel
      → Tool pipeline (effects)
      → EventEnvelope journal
      → RunResult
UI / dashboard
  ← reducer over same events
```

- Route CLI and REPL through `ApplicationRunService`
- JSONL compatibility adapters retained
- Replayable events + reducer-based UI
- Acceptance: supplied transcript replays without duplicate prompts, leaked reasoning, unnecessary pytest, false completion, or out-of-scope actions

### 7.5 Dashboard P2

- Preserve existing uncommitted `dashboard.html`
- Loading, network failure, rate-limit, stale-data states
- Avoid unannounced external requests where possible
- Browser smoke or documented manual verification; separate from core Python suite

---

## 8. Acceptance criteria

- No completion crash from prompt-cache statistics (`session.cache_hit_tokens`, never `.stats`)
- HTML edit never causes unrelated pytest execution
- User can reliably type approval choices while Kite is working
- Approval choices interactive/clickable when terminal supports it
- Only one terminal input reader active at any time
- No unsupported “done” or “tests passed” claim reaches the final response
- No installation, memory mutation, network side effect, destructive action, or subagent starts without required approval
- Nested agents inherit restrictions and cannot elevate
- Original transcript can be replayed deterministically without the observed failures

---

## 9. Test strategy

Deterministic fake-provider and replay tests for:

- Cache persistence after successful completion
- HTML-only edits not invoking pytest; Python/mixed selecting correct checks
- Failed or unrelated commands not satisfying verification
- Unsupported completion claims rejected
- Approval input while follow-up composer active; keyboard (and mouse where supported)
- EOF / Ctrl+C / disconnect during approval
- Exactly one approval panel and one approval reason
- Skill install, durable memory, network, subagents request approval
- Nested agents inherit restrictions; malicious repo instructions fail to widen permissions
- Windows command guidance; process cancellation; bounded retries
- Non-agent-compatible models filtered or warned
- Full replay of supplied transcript against acceptance criteria

CI: Windows and Linux × Python 3.11 and 3.12, fake providers only.

---

## 10. Global constraints

- Fake providers only in unit/CI
- Preserve `dashboard.html` user diff
- Graduated autonomy default; mandatory effects always confirm
- `--no-guardrails` visibly high-risk
- Small diffs; update `kite_commands.md` and/or `docs/cli-ux.md` when UX changes
- Glossary changes → `CONTEXT.md`; prompt changes → `data/prompts/`
- Do not import UI from `agent/`; do not call LiteLLM from `ui/repl.py` directly

---

## 11. Explicit non-goals (this program)

- omp² convars, Director stack, XML session DOM, full in-process Bash interpreter
- Replacing Rich/prompt_toolkit with a new TUI framework
- Live provider calls in unit tests
- Making dashboard checks part of core Python verification
- Reverting or rewriting the user’s uncommitted dashboard work beyond additive robustness states

---

## 12. Implementation follow-up

After this spec is reviewed:

1. Write per-train plans in `docs/superpowers/plans/` (TDD, bite-sized, exact files/tests)
2. Execute via parallel subagents per wave with review gates
3. Land trains independently where possible; keep hot-file trains sequential
