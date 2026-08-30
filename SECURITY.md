# Security policy

## Supported versions

Security fixes are applied to the latest released version of Kite.

| Version | Supported |
|---------|-----------|
| 0.6.x   | yes |
| < 0.6   | no |

## Reporting a vulnerability

If you find a security issue in Kite, please report it privately rather than opening a public issue.

- Email the maintainer (see the GitHub profile for KhanUzeb).
- Include a description of the issue, steps to reproduce, and any relevant logs.
- Expect an acknowledgement within a few days.

## Scope and trust model

Kite runs tools against your local workspace. Its guardrails protect against **model mistakes** (path escapes, destructive bash, secret-shaped writes), not against a hostile operator on the same machine. Do not run Kite with untrusted task text, and avoid `--no-guardrails` outside trusted, local automation.

API keys live in `~/.kite/.env` (or the repo `.env`, which is gitignored). Never commit keys. If a key is leaked, rotate it immediately.
