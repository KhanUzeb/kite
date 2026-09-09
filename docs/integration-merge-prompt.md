# Integration merge prompt — review, fix, and merge all Kite PRs to `main`

Use this document as a **mega prompt** for a local Cursor agent (e.g. Grok 4.6). Paste the entire **Agent instructions** section below into a new agent session.

---

## Agent instructions

### Your mission

You are working on the **Kite** repo (`https://github.com/KhanUzeb/kite`, Python 3.11+ agent harness). There are **11 open draft PRs** (#49–#59) that must **all land on `main`**. Your job:

1. **Review** every PR (code, tests, docs, CI, conflicts).
2. **Fix** anything broken (failing CI, merge conflicts, ruff, missing tests).
3. **Integrate** parallel branches into one coherent stack on `main`.
4. **Push** fixes and **merge** everything to `main` in a safe order.
5. **Close** all PRs with accurate merge commits or squash notes.

Do **not** skip PRs. Do **not** leave draft PRs open when done.

---

### Repo context

- **Package:** `src/kite/`, entry `kite.cli.run:main`
- **Tests:** `pytest` from repo root (CI: Python 3.11 + 3.12, Ubuntu + Windows)
- **Lint:** `ruff check src tests`
- **Config:** `~/.kite/` (never commit secrets)
- **Agent guide:** read `AGENTS.md`, `CONTEXT.md`, `SECURITY.md`, `CONTRIBUTING.md`
- **Branch naming:** `cursor/<descriptive-name>-4709`

---

### Open PR inventory

| PR | Branch | Base | Title | CI (last known) |
|----|--------|------|-------|-----------------|
| #49 | `cursor/byos-auth-refactor-4709` | `main` | BYOS auth via official provider runtimes | **FAILING** |
| #50 | `cursor/security-hardening-4709` | `main` | Security hardening phases 6–11 | PASS |
| #51 | `cursor/themes-tui-4709` | `cursor/security-hardening-4709` | Themes + TUI palettes | PASS |
| #52 | `cursor/security-hardening-more-4709` | `cursor/security-hardening-4709` | Meta redaction, SSRF, attach guard | PASS |
| #53 | `cursor/subagents-orchestration-4709` | `cursor/security-hardening-more-4709` | Subagent orchestration + crew TUI | PASS |
| #54 | `cursor/slash-startup-perf-4709` | `cursor/security-hardening-4709` | Faster `/` completion in REPL | PASS |
| #55 | `cursor/working-style-memory-4709` | `cursor/slash-startup-perf-4709` | Working rhythm memory | PASS |
| #56 | `cursor/user-context-subagents-4709` | `cursor/working-style-memory-4709` | USER/PROFILE, personas, live crew | PASS |
| #57 | `cursor/subagent-cli-ux-4709` | `cursor/user-context-subagents-4709` | `kite subagents` CLI + `/agents` UX | PASS |
| #58 | `cursor/resume-goal-recovery-4709` | `cursor/subagent-cli-ux-4709` | `/goal`, recovery, resume UX | PASS |
| #59 | `cursor/web-tools-improve-4709` | `cursor/resume-goal-recovery-4709` | webfetch/websearch + harness OS protection | PASS |

**Tip of main feature stack:** `cursor/web-tools-improve-4709` (~31 commits above `main`).

Verify with:

```bash
gh pr list --state open
git fetch origin
```

---

### Branch dependency graph

```
main
├── #49 byos-auth-refactor (parallel, failing CI)
└── #50 security-hardening
    ├── #51 themes-tui
    ├── #52 security-hardening-more
    │   └── #53 subagents-orchestration
    └── #54 slash-startup-perf
        └── #55 working-style-memory
            └── #56 user-context-subagents
                └── #57 subagent-cli-ux
                    └── #58 resume-goal-recovery
                        └── #59 web-tools-improve  ← integration tip
```

**Parallel forks from #50:** themes (#51), security-more → orchestration (#52 → #53), slash-perf chain (#54 → … → #59).

**#49** is independent of the security-hardening tree.

---

### What each PR area touches (review focus)

#### #50 Security hardening

- `src/kite/guardrails/`, path sandbox, bash policy, secret redaction
- `SECURITY.md`, session policy

#### #51 Themes

- `src/kite/ui/theme.py`, render/style, REPL colors

#### #52 Security hardening more

- Meta redaction in sessions, SSRF userinfo, attach path guard
- `tests/test_security_hardening_more.py`

#### #53 Subagent orchestration

- `src/kite/agent/orchestrator.py`, crew TUI, jobs registry

#### #54 Slash startup perf

- `src/kite/ui/complete.py`, `src/kite/cli/slash.py` lazy loading

#### #55 Working style memory

- `src/kite/memory/` working rhythm, `WORKING.md` injection

#### #56 User context + subagents

- `USER.md` / `PROFILE.md`, bundled personas, headless tasks
- `src/kite/tasks/headless.py`, `src/kite/cli/tasks.py`

#### #57 Subagent CLI UX

- `src/kite/cli/subagents.py`, `/agents` REPL, `harness_build.py`

#### #58 Goal + recovery

- `src/kite/memory/goal.py`, `recovery.py`, `/goal`, `kite resume --retry`
- `tests/test_recovery_goal.py`

#### #59 Web tools + harness OS protection

- `src/kite/tools/web.py` — webfetch/websearch improvements
- `src/kite/guardrails/ssrf.py` — connect-time peer validation, redirect caps
- `src/kite/guardrails/sandbox.py` — `/proc` `/sys` `/dev` protection, bash denylist
- `src/kite/application/policy/engine.py` — restricted mode blocks all network tools
- `tests/test_web.py`, `tests/test_harness_system_protection.py`
- **485 tests** passing at last verify

#### #49 BYOS auth (needs fix)

- `src/kite/providers/auth/`, Codex/Claude/Grok subscription flows
- **CI failing** — fix first or merge last after rebasing on integrated tip

---

### Integration strategy (required)

Do **not** merge PRs one-by-one into `main` in PR number order. Use an **integration branch**.

#### Phase 1 — Bootstrap

```bash
git fetch origin main
git checkout main && git pull origin main
git checkout -b cursor/integration-merge-4709
```

#### Phase 2 — Merge primary stack (tip = #59)

```bash
git merge origin/cursor/web-tools-improve-4709
# Resolve conflicts; run pytest + ruff
```

This should include #50 → #54 → #55 → #56 → #57 → #58 → #59 in one history.

#### Phase 3 — Merge parallel branches onto integration tip

Merge in this order (resolve conflicts after each):

1. `origin/cursor/security-hardening-more-4709` + `origin/cursor/subagents-orchestration-4709`  
   If already in stack, verify no duplicate commits; skip if redundant.
2. `origin/cursor/themes-tui-4709`
3. `origin/cursor/byos-auth-refactor-4709` (fix CI failures here)

After each merge:

```bash
pytest -q
ruff check src tests
```

#### Phase 4 — Verify harness-wide security

Confirm these behaviors (see `SECURITY.md`):

- `/proc`, `/sys`, `/dev` blocked for read/write/bash
- SSRF: private IPs, metadata hosts, connect-time peer check
- `restricted` mode blocks bash network + webfetch/websearch/webcrawl + Context7
- Child subprocess env filtered (bash, rg, gh, jobs)
- No `--no-guardrails` regressions in default config

#### Phase 5 — Push and merge to main

```bash
git push -u origin cursor/integration-merge-4709
# Open PR: base main, or merge locally if you have rights:
git checkout main && git merge cursor/integration-merge-4709
git push origin main
```

#### Phase 6 — Close all original PRs

For each #49–#59: mark merged/closed with a comment pointing to the integration commit on `main`.

---

### Review checklist (every PR)

- [ ] `pytest` passes (3.11 minimum; run full matrix if possible)
- [ ] `ruff check src tests` clean
- [ ] `scripts/sync_version.py --check` if version files touched
- [ ] No committed secrets, `.env`, or API keys
- [ ] User-facing behavior documented in `kite_commands.md`
- [ ] Glossary/architecture updates in `CONTEXT.md` / `architecture.md` if needed
- [ ] `SECURITY.md` accurate for guardrail changes
- [ ] Small, focused diffs — no unrelated churn
- [ ] Stacked PR bases obsolete after integration — close, don't re-merge individually

---

### Known issues to fix

1. **#49 CI failing** — run `pytest -q` on `cursor/byos-auth-refactor-4709`, fix failures, rebase on integration tip.
2. **Parallel fork conflicts** — themes (#51) vs slash-perf (#54) both touch `ui/`; orchestration (#53) vs user-context (#56) may overlap `agent/` and `jobs.py`. Prefer **newer tip behavior** when resolving; run tests after each resolution.
3. **Draft PRs** — convert to ready or merge via integration PR; **all must be merged**, not left open.
4. **Duplicate security work** — #52 and parts of #59 both touch SSRF; keep stricter/latest implementation, drop duplicates.

---

### Commands cheat sheet

```bash
./scripts/install.sh          # dev setup
pytest -q                     # full suite
pytest tests/test_web.py tests/test_harness_system_protection.py -q
ruff check src tests
kite bench --check            # harness timing budgets (optional)

gh pr list --state open
gh pr view 59
gh pr checks 49
gh run list --branch cursor/web-tools-improve-4709
```

---

### Success criteria

- [ ] `main` contains **all** features from PRs #49–#59
- [ ] **All 11 PRs closed** (merged or superseded by integration PR)
- [ ] CI green on `main`
- [ ] `pytest` ≥ 485 tests passing locally
- [ ] No open draft PRs left for this batch
- [ ] Brief merge summary comment on the integration PR listing what landed

---

### Constraints

- **Do not** use `--no-guardrails` to make tests pass.
- **Do not** weaken SSRF or OS path protections to unblock merges.
- **Do not** force-push `main`.
- Match existing code style; read surrounding files before editing.
- Prefer **merge** or **rebase integration branch** over cherry-picking 31 commits manually.

---

### Optional: single-shot merge if stack is clean

If `origin/cursor/web-tools-improve-4709` already contains the full #50 → #59 chain and parallel branches are redundant:

```bash
git checkout main && git pull
git merge origin/cursor/web-tools-improve-4709
git merge origin/cursor/themes-tui-4709
git merge origin/cursor/subagents-orchestration-4709
git merge origin/cursor/byos-auth-refactor-4709  # fix conflicts + CI
pytest -q && ruff check src tests
git push origin main
```

Then close #49–#59 as merged.

---

**Start by running `gh pr list --state open` and `git fetch origin` to confirm branches haven't changed, then execute Phase 1.**
