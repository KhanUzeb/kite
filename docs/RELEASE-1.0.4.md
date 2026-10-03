# Kite v1.0.4

**Date:** 2026-10-03

Security-hardening release. Fixes all 9 findings from the adversarial audit
(trust boundaries, session durability, usage accounting, context freshness)
and consolidates the test suite below the 150-test CI budget.

## Security fixes (High)

- **Project extensions gated on trust (F-01).** Project-local
  `.kite/extensions` no longer executes on load. Only user-global
  `~/.kite/extensions` loads until the workspace is explicitly trusted;
  headless runs (no trust prompt) stay untrusted. `no_extensions` still
  disables everything. `SECURITY.md` now states the exact behavior.
- **GitHub token scoped to lone `gh` (F-02).** Ambient `GH_TOKEN` /
  `GITHUB_TOKEN` are injected only into a single `gh …` subprocess, never
  into a chained shell (`gh …; <other>`, pipes, `&&`, substitutions).
  Compound commands can no longer exfiltrate the token to sibling processes.

## Correctness fixes (Medium)

- **Session events survive rewrites (F-03).** `_write_meta` re-appends
  durable `event` / `context_checkpoint` rows, so `set_exit`, `save`, and
  compaction snapshots no longer wipe the audit trail.
- **Atomic session snapshots (F-04).** Session files rewrite via
  temp-file + `os.replace` with owner-only perms; an interrupted write
  leaves the prior transcript intact.

## Edge-case fixes (Low)

- **Non-object JSONL skipped (F-05).** `null`, lists, strings, and numbers
  in session files are skipped instead of aborting `load_session` / resume.
- **Cache accounting (F-06).** OpenAI-style `cached_tokens` (a subset of
  `prompt_tokens`) no longer double-counts: 1000 prompt / 500 cached now
  reports 1000 input and 50% hit ratio instead of 1500 and 33%.
- **Stale context cache (F-07).** Instruction-file and commit fingerprint
  invalidates the 120s project-context cache; `git status` refreshes on
  cache hits so edits surface immediately.
- **Authorized `git push` (F-08).** Plain `push` / `clone` flow to the
  approval path (SERIOUS remote-write) instead of a permanent hard-block;
  only `--force` / `-f` (except `--force-with-lease`) stays hard-denied.
- **Agy prompt ceiling (F-09).** `flatten_prompt` enforces the 24k-char
  hard bound after composing system + retained turns, and the `agy`
  subprocess inherits a filtered environment (no credential keys).

## Tests

Suite consolidated 305 → **114 collected** (113 passed, 1 platform skip)
with identical assertions — batched per domain module, headroom for
regression tests under the 150 cap. New regression tests cover every
finding above.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.4
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.4] entry.
