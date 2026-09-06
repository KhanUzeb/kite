# Security policy

## Supported versions

Security fixes are applied to the latest released version of Kite.

| Version | Supported |
|---------|-----------|
| 0.9.x   | yes |
| 0.8.x   | yes |
| 0.7.x   | yes |
| < 0.7   | no |

## Reporting a vulnerability

If you find a security issue in Kite, please report it privately rather than opening a public issue.

- Email the maintainer (see the GitHub profile for KhanUzeb).
- Include a description of the issue, steps to reproduce, and any relevant logs.
- Expect an acknowledgement within a few days.

## Scope and trust model

Kite runs tools against your local workspace. Its guardrails protect against **model mistakes** (path escapes, destructive bash, secret-shaped writes), not against a hostile operator on the same machine. Do not run Kite with untrusted task text, and avoid `--no-guardrails` outside trusted, local automation.

**Execution mode:** default `host` keeps file and bash access outside the session cwd (protected paths like `.ssh`, system dirs, `.env` still blocked). `restricted` mode clamps paths to the session sandbox. Production tool calls also pass through **`PolicyEngine`** (path/network authorization). Toggle in the REPL with `/restricted on|off`, or set `[guardrails] execution_mode = "restricted"` in runtime config. Only use host mode when you understand the blast radius.

API keys live in `~/.kite/.env` (or the repo `.env`, which is gitignored). Never commit keys. If a key is leaked, rotate it immediately.
