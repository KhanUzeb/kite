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

**Known limits:** Secret redaction is pattern-based (not exhaustive). `/attach` and `/clip` still read user-selected paths, but **protected** credential paths (e.g. `.env`, `~/.ssh`, `~/.kite/.env`) are refused. Global skill trees under `~/.kite/skills` are readable in restricted mode (symlink/junction targets included). Approval decisions and tool events may be retained in `~/.kite/approvals.json` and `~/.kite/audit.jsonl` until you delete them (owner-only `chmod 600`).

## Session persistence

Session transcripts are stored under `~/.kite/sessions/` as JSONL. Configure persistence in `~/.kite/config.toml`:

```toml
session_persistence = "redacted"  # full | redacted | disabled (default: redacted)
```

| Mode | Behavior |
|------|----------|
| `redacted` (default) | Messages, tool args/results, events, and **meta fields** (task, label, cwd) are recursively sanitized before write. Session files are owner-only (`chmod 600`). |
| `full` | Persist raw payloads (opt-in; may retain secrets and proprietary content). |
| `disabled` | No session file writes; in-memory session only for the current run. |

Redaction uses the same recursive sanitizer as audit logs and event persistence. Sensitive key names (token, password, authorization, etc.) and inline patterns (Bearer tokens, cookies, PKCE verifiers) are replaced with `[REDACTED]`.

## Skill trust model

Skills are model instructions — treat them as a supply-chain / prompt-injection boundary.

| Origin | Trust | Notes |
|--------|-------|-------|
| `bundled` | **trusted** | Shipped with Kite under `data/skills`. |
| `user-local` | untrusted | Manually placed under `~/.kite/skills` or `~/.agents/skills`. |
| `project` | untrusted | From `<repo>/.kite/skills` or `.agents/skills`. |
| `npm` / `git` / `link` | untrusted | Installed via `skill install=…`; provenance recorded in `.kite-provenance.json`. |
| `plugin` | untrusted | From `.kite/plugins` discovery. |

The model sees `trust`, `origin`, and `source` attributes in skill listings and invocations. Remote skills never silently inherit bundled trust. Skills cannot bypass Kite guardrails or security policies.

## User-authored memory (USER / PROFILE / WORKING)

Files under `~/.kite/memory/` (`USER.md`, `PROFILE.md`, `WORKING.md`, `MEMORY.md`) are **user-authored**. When injected into the system prompt they are wrapped in `<!-- kite:untrusted -->` delimiters — same boundary as npm/git skills. The model must not treat them as overriding safety, guardrails, or credentials policy.

- Writes use owner-only permissions (`chmod 600`) via `secure_memory_write`.
- Note/signal text is length-capped at write time.
- Nested subagents (`no_context`) do **not** receive global user identity blocks.

## Subagent profiles and orchestration

| Control | Limit |
|---------|-------|
| Bundled profiles | `src/kite/data/subagents/*.md` — trusted |
| Custom profiles | `~/.kite/subagents/*.md` only; path-confined; 32KB max; untrusted wrapper in composed prompt |
| Crew size | Max **12** workers per `subagent` dispatch (sync or background) |
| Nested tools | No `subagent` recursion; no `memory` writes from nested workers |
| Live crew UI | `/live agents` redacts streamed output and prompt previews |

Background job output (`job_output`) is redacted before display, matching foreground bash streaming.

## Child process environment

Before spawning subprocesses, Kite filters credential-like keys from the parent environment. Keys passed via `extra` env overrides that match sensitive patterns (e.g. `OPENAI_API_KEY`, `GITHUB_TOKEN`) are **refused** — they cannot reintroduce secrets after filtering.

## Subprocess teardown

Foreground bash, `ProcessRunner`, and background jobs run children in isolated process groups. Timeout and cancellation terminate the full process tree (Unix: `killpg`; Windows: `taskkill /T`).

## SSRF protections

HTTP tools resolve hostnames, validate every resolved address against private/loopback/link-local/metadata ranges, reject URLs with embedded credentials (`user:pass@host`), re-validate immediately before connect (DNS TOCTOU mitigation), and re-check redirect targets. Alternate IPv4 encodings (decimal, hex, octal) are blocked.

**Execution mode:** default `host` keeps file and bash access outside the session cwd (protected paths like `.ssh`, system dirs, `.env` still blocked). `restricted` mode clamps paths to the session sandbox. Production tool calls also pass through **`PolicyEngine`** (path/network authorization). Toggle in the REPL with `/restricted on|off`, or set `[guardrails] execution_mode = "restricted"` in runtime config. Only use host mode when you understand the blast radius.

API keys live in `~/.kite/.env` (or the repo `.env`, which is gitignored). Never commit keys. If a key is leaked, rotate it immediately.

**BYOS (subscription) authentication** uses each provider's official runtime locally — Kite does not operate a shared provider account, credential proxy, or remote authentication server. There is no telemetry of OAuth tokens, account identifiers, or authentication events.

| Provider | Mechanism | Credential store |
|----------|-----------|------------------|
| ChatGPT / Codex | `openai-codex` SDK (`Codex.login_chatgpt`, device code, `account`, `logout`) | `~/.codex/` (Codex runtime) |
| Claude subscription | Claude Code CLI (`claude auth login/status/logout`) | Claude Code (Keychain or platform store) |
| Grok subscription | `grok` CLI (`grok login`, `--device-auth`, `logout`) | `~/.grok/auth.json` |
| xAI API (BYOK) | `XAI_API_KEY` in `~/.kite/.env` | `~/.kite/.env` |

Kite never copies subscription OAuth tokens into `~/.kite/.env` or logs access/refresh tokens.
