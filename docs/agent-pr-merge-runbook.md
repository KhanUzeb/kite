# Agent runbook: merge Kite v0.7.1 release PR

**Copy everything below the `---` line into a new Cursor Cloud Agent (or paste as the user message).**

Repo: `https://github.com/KhanUzeb/kite`  
Base branch: `main` (currently **v0.6.8**)  
**Only PR to merge:** [#18](https://github.com/KhanUzeb/kite/pull/18) — `cursor/release-0.7.1-8708` → `main`  
**Do not merge** PRs #7–#17 individually (already folded into #18).

---

## Your task

Systematically merge **PR #18** into `main`, verify the release, publish the GitHub release, and **close** superseded PRs #7–#17 with a short comment. Do not create new feature branches unless CI fails and a fix is required.

## Context

| PR | Branch | Action |
|----|--------|--------|
| **#18** | `cursor/release-0.7.1-8708` | **MERGE** → `main` |
| #15 | `cursor/release-0.7.0-8708` | Close — superseded by #18 |
| #16 | `cursor/ui-tool-cards-8708` | Close — in #18 |
| #17 | `cursor/setup-onboarding-8708` | Close — in #18 |
| #7–#14 | feature branches | Close — in #18 |

Release includes: harness upgrade (bench, ToolResult, execution cwd, checkpoints, handoff), tool cards UI, setup onboarding, CI always-on pytest, version **0.7.1**. Tag `v0.7.1` already exists on the release branch.

## Preconditions (run before merge)

```bash
git fetch origin main cursor/release-0.7.1-8708
gh pr view 18 --json mergeable,state,statusCheckRollup
gh pr checks 18
```

**Stop if:**
- PR #18 is not `MERGEABLE`
- Required CI checks are failing (re-run workflow or fix on `cursor/release-0.7.1-8708` first)

## Step 1 — Local verification (release branch)

```bash
git checkout cursor/release-0.7.1-8708
git pull origin cursor/release-0.7.1-8708
uv pip install -e ".[dev]"
export KITE_HOME="${TMPDIR:-/tmp}/kite-verify-$$"
export KITE_SKIP_SETUP=1
pytest -q
kite --version   # must print 0.7.1
```

**Pass criteria:** pytest exits 0; `kite --version` is `0.7.1`.

## Step 2 — Merge PR #18

Use GitHub (preferred):

```bash
gh pr merge 18 --merge --delete-branch=false
```

Or squash if maintainers prefer one commit on `main`:

```bash
gh pr merge 18 --squash --delete-branch=false
```

**Do not** merge #7–#17.

## Step 3 — Verify `main` after merge

```bash
git fetch origin main
git checkout main
git pull origin main
grep '^version' pyproject.toml          # expect: version = "0.7.1"
python -c "from kite import __version__; print(__version__)"  # expect: 0.7.1
pytest -q
```

Wait for CI on `main` to complete (pytest 3.11 + 3.12). CI runs automatically on every push to `main`.

```bash
gh run list --branch main --limit 3
```

## Step 4 — Publish GitHub release

Tag `v0.7.1` should point at the release commit. Publish the draft release using notes from `docs/RELEASE-0.7.1.md`:

```bash
gh release view v0.7.1 2>/dev/null || gh release create v0.7.1 --notes-file docs/RELEASE-0.7.1.md --title "Kite v0.7.1"
# If draft exists:
gh release edit v0.7.1 --notes-file docs/RELEASE-0.7.1.md --draft=false
```

## Step 5 — Close superseded PRs

For each PR **#7, #8, #9, #10, #11, #12, #13, #14, #15, #16, #17**, close with comment:

> Superseded by #18 (merged to `main` as v0.7.1). No separate merge needed.

```bash
for n in 7 8 9 10 11 12 13 14 15 16 17; do
  gh pr close "$n" --comment "Superseded by #18 (merged to main as v0.7.1). No separate merge needed."
done
```

## Step 6 — Final report

Reply to the user with:

1. Merge commit SHA on `main`
2. CI status (link to latest `main` workflow run)
3. Release URL for v0.7.1
4. List of closed PRs
5. `pytest` count on `main`
6. Any blockers encountered

## Anti-patterns (do NOT do)

- Merge feature PRs #7–#17 before or after #18 (duplicate/conflict risk)
- Bump version again (already 0.7.1 in #18)
- Delete `cursor/release-0.7.1-8708` before merge completes
- Merge #15 and #18 both (pick #18 only)

## Optional smoke on clean machine

```bash
./scripts/install.sh --no-clone --verify
kite setup   # interactive; skip with KITE_SKIP_SETUP=1 in CI
kite bench --json
```

---

## Verification script (repo root)

Run from a checkout of `cursor/release-0.7.1-8708` or `main` after merge:

```bash
./scripts/verify_release_pr.sh
```
