# Kite Remaining User-Flow Issues Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with test-first changes and a review checkpoint after each task.

**Goal:** Remove the remaining verified end-to-end user-flow failures that are outside the approval-safety PR.

**Architecture:** Keep the CLI, readiness, provider, and headless layers honest about the state they expose. Each entry point must either carry a user option into `HarnessConfig` or reject it, and every displayed success/readiness state must match executable runtime behavior.

**Tech Stack:** Python 3.11+, argparse, Rich, prompt_toolkit, pytest.

**Spec:** `plan.md` — requirements captured from the verified 2026-09-09 user-flow audit.

## Global Constraints

- Do not make live model-provider calls in unit tests.
- Preserve the CLI/UI → application → runtime → agent layer boundary.
- Keep session persistence and secret-redaction behavior unchanged.
- Update `kite_commands.md` whenever user-visible command behavior changes.
- Run focused tests first, then `pytest -q` and `./scripts/lint.sh` before merging.

---

### Task 1: Make Headless Completion Status Truthful

**Files:**
- Modify: `src/kite/tasks/headless.py`
- Modify: `src/kite/cli/tasks.py`
- Test: `tests/test_headless_tasks.py`

**Interfaces:**
- Consumes: legacy harness `exit_status` values.
- Produces: `HeadlessTaskResult.ok`, `HeadlessBatchResult.ok`, JSON `succeeded`, and the `kite tasks run` process exit code.

- [ ] **Step 1: Write failing status tests**

Add parameterized tests proving only `Submitted` is successful. `LimitsExceeded`, `TimeExceeded`, `Stalled`, `ProviderFault`, `Interrupted`, and `Error` must set `ok=False`; a batch containing any of them must set `batch.ok=False` and report zero successful tasks.

- [ ] **Step 2: Run the focused tests and confirm the false-green behavior**

Run: `pytest tests/test_headless_tasks.py -q`

Expected failure: `Stalled` and `LimitsExceeded` are currently counted as successful.

- [ ] **Step 3: Correct the result mapping**

Set task success from the canonical completed state only:

```python
ok = exit_status == "Submitted"
```

Keep the original `exit_status`, session id, submission, and error in JSON so callers can distinguish retryable interruptions from hard failures.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_headless_tasks.py -q`

- [ ] **Step 5: Update command documentation**

Document that incomplete, stalled, interrupted, and provider-faulted tasks return a non-zero batch exit code even when their sessions remain resumable.

---

### Task 2: Eliminate Silently Ignored CLI Flags

**Files:**
- Modify: `src/kite/cli/run.py`
- Modify: `src/kite/ui/repl.py`
- Modify: `src/kite/agent/harness_build.py` only if a missing field cannot already be expressed.
- Test: `tests/test_cli_misc.py`
- Test: `tests/test_repl_misc.py`

**Interfaces:**
- Consumes: parsed `run`, `chat`, and `resume` arguments.
- Produces: `ChatSession` constructor state and the eventual `HarnessConfig`.

- [ ] **Step 1: Write failing chat flag-plumbing tests**

Patch `ChatSession` at the CLI boundary and assert that `--steps`, `--cost`, `--time`, `--no-context`, `--no-compact`, `--no-guardrails`, `--attach`, `--role`, and `--long` are either carried into the interactive session or rejected by argparse. The command must never accept and discard them.

- [ ] **Step 2: Write failing resume flag-plumbing tests**

Cover both branches:

```text
kite resume <id>                 -> interactive chat
kite resume <id> "continue"      -> one-shot continuation
```

Assert that `--time`, `--role`, `--output`, and `--json` have explicit behavior in the one-shot branch, and that one-shot-only flags produce a clear usage error in the interactive branch.

- [ ] **Step 3: Split parser flags by execution shape**

Replace the single `_add_run_flags()` bucket with small composable groups:

```python
_add_model_workspace_flags(parser)
_add_budget_flags(parser)
_add_interactive_flags(parser)
_add_one_shot_output_flags(parser)
```

`chat` must not advertise `--headless`, `--no-stream`, `--json`, `--quiet`, or trajectory output unless those behaviors are implemented. `run` and one-shot `resume` retain machine-output flags.

- [ ] **Step 4: Carry supported interactive options into each harness**

Extend `ChatSession` with explicit fields for budgets, context/compaction/guardrails, role, long-task mode, and startup attachments. Feed those fields to `build_harness_config()` inside `_make_harness()`.

- [ ] **Step 5: Verify missing attachments fail before the REPL starts**

Run a CLI test equivalent to:

```text
kite chat --attach /definitely/missing
```

Expected: exit code 2 with a concrete file error, not a successful REPL launch.

- [ ] **Step 6: Verify focused CLI and REPL suites**

Run: `pytest tests/test_cli_misc.py tests/test_repl_misc.py -q`

---

### Task 3: Remove the Claude Subscription Dead End

**Files:**
- Modify: `src/kite/providers/credentials.py`
- Modify: `src/kite/providers/resolve.py`
- Modify: `src/kite/config/readiness.py`
- Modify: `src/kite/providers/select.py`
- Modify: `src/kite/data/catalog.toml`
- Test: `tests/test_credentials.py`
- Test: `tests/test_byos.py`
- Test: `tests/test_byos_ux.py`

**Interfaces:**
- Consumes: Claude Code CLI authentication status and Anthropic API-key status.
- Produces: provider-table status, setup readiness, model selection eligibility, and runtime credential errors.

- [ ] **Step 1: Write a failing linked-but-unusable provider test**

Simulate Claude Code reporting an authenticated subscription while `ANTHROPIC_API_KEY` is absent. Assert that Kite does not label the provider `Ready`, does not include it in executable-provider hints, and does not suggest repeating `claude auth login`.

- [ ] **Step 2: Separate authentication status from model-call readiness**

Introduce a typed provider status carrying both concepts:

```python
@dataclass(frozen=True)
class ProviderCredentialStatus:
    provider: str
    linked: bool
    usable: bool
    method: str
    detail: str
```

Claude Code authentication without an Anthropic API key is `linked=True`, `usable=False`. ChatGPT/Codex and any genuinely bridged subscription remain usable according to their model backend.

- [ ] **Step 3: Correct setup and selection copy**

Display Claude as `CLI linked · API key required for Kite` and offer `kite keys --set anthropic`. Remove claims that Claude Code subscription billing currently powers Kite model calls.

- [ ] **Step 4: Prevent unusable providers from completing setup**

Provider selection may show linked status, but setup must not print `Ready` or persist Claude as the executable default until the runtime credential check passes.

- [ ] **Step 5: Verify credential and BYOS suites**

Run: `pytest tests/test_credentials.py tests/test_byos.py tests/test_byos_ux.py -q`

---

### Task 4: Gate Tasks on Readiness Before Starting Work

**Files:**
- Modify: `src/kite/ui/repl.py`
- Modify: `src/kite/config/readiness.py`
- Modify: `src/kite/cli/setup.py`
- Test: `tests/test_repl_misc.py`
- Test: `tests/test_cli_misc.py`

**Interfaces:**
- Consumes: `SetupStatus` for the selected provider/model.
- Produces: first-run setup offer and REPL task admission.

- [ ] **Step 1: Write a failing REPL admission test**

With no executable provider/model, submit a normal task and assert that no harness is created, no running state starts, no session is created, and the setup banner is printed once.

- [ ] **Step 2: Replace freshness-only setup prompting**

Base the first-run offer on `SetupStatus.ready`, not merely the presence of config or any linked credential. A linked-but-unusable provider must not suppress setup.

- [ ] **Step 3: Add a synchronous readiness gate to `_run_task()`**

Validate attachments, resolve the selected provider/model, call the canonical readiness check, and return to the composer with `/setup`, `/login`, and `/select` actions before setting `running_label` or spawning the worker.

- [ ] **Step 4: Verify first-run and REPL tests**

Run: `pytest tests/test_cli_misc.py tests/test_repl_misc.py tests/test_byos_ux.py -q`

---

### Task 5: Make Help Output Match the Parser

**Files:**
- Modify: `src/kite/cli/help_map.py`
- Modify: `src/kite/cli/run.py`
- Modify: `kite_commands.md`
- Test: `tests/test_cli_misc.py`

**Interfaces:**
- Consumes: argparse command definitions.
- Produces: `kite --help`, `kite help`, and documented examples.

- [ ] **Step 1: Write failing help-contract tests**

Extract documented long options from `kite help` and assert each appears in the relevant argparse help. Assert the hidden maintainer command does not render as `==SUPPRESS==`.

- [ ] **Step 2: Remove the invalid run/chat/resume `--auto-compact` claim**

Keep the real persistent form only:

```text
kite config --auto-compact true|false
```

- [ ] **Step 3: Hide maintainer commands cleanly**

Exclude the maintainer parser from the public subcommand help list while retaining direct parsing for authorized maintainers.

- [ ] **Step 4: Remove duplicated command-guide prose**

Delete the repeated tool-philosophy sentence in `kite_commands.md` and synchronize headless/interactive flag tables with Task 2.

- [ ] **Step 5: Verify CLI help**

Run: `pytest tests/test_cli_misc.py -q`

---

### Task 6: Add a Narrow-Terminal Provider View

**Files:**
- Modify: `src/kite/cli/run.py`
- Modify: `src/kite/cli/setup.py`
- Test: `tests/test_cli_misc.py`

**Interfaces:**
- Consumes: Rich console width and provider readiness rows.
- Produces: readable `kite providers` and `kite keys` output.

- [ ] **Step 1: Write a failing 50-column rendering test**

Render provider status at width 50 and assert the default marker remains on the provider name, provider names are distinguishable, and the selected model/status remain readable without one-character orphan lines.

- [ ] **Step 2: Select a compact layout below 72 columns**

Use three columns: `provider`, `model`, and `status`. Move display name and auth method into a short second line only when needed. Keep the existing five-column table for wider terminals.

- [ ] **Step 3: Verify narrow and normal layouts**

Run: `pytest tests/test_cli_misc.py -q`

---

### Final Verification

- [ ] Run: `pytest -q`
- [ ] Run: `./scripts/lint.sh`
- [ ] Run: `COLUMNS=50 python -m kite providers`
- [ ] Run: `python -m kite help`
- [ ] Run: `python -m kite chat --attach /definitely/missing`
- [ ] Confirm `git status --short` contains only the planned files.
