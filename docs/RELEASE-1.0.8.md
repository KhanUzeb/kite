# Kite v1.0.8

**Date:** 2026-10-12

## Highlights

Safer worker boundaries and more useful provider failures: scoped subagents cannot write outside their declared paths, Antigravity retries only transient failures, and auth/model errors now explain the next step. Restricted-mode pushes remain approval-controlled rather than being rejected outright.

## Model and provider reliability

- Antigravity network, service, rate-limit, and 5xx failures use Kite's bounded retry policy. Authentication, quota, and malformed-response errors are not retried.
- Provider and model errors distinguish common connection, service, rate-limit, and authentication failures, redact sensitive values, and give a next action.
- Antigravity is shown as linked only after `agy models` verifies the session.

## Security and subagents

- A subagent's optional `scope` bounds workspace file mutations before execution. An empty scope allows no writes; scoped workers cannot use mutating bash commands because their targets cannot be reliably constrained.
- User memory and gathered repository metadata are marked as untrusted prompt data, with forged closing markers escaped.
- SSRF-protected HTTP fetches connect directly instead of honoring proxy environment variables, so connected-peer checks validate the destination. Configure any required proxy outside these guarded requests.
- In restricted mode, ordinary `git push` follows the existing network approval policy. Force-push remains blocked.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.8
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.8] entry.
