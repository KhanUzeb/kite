# Ideal CLI Spec Coverage (Kite 0.6)

Mapping of the 14-category Ideal Coding CLI spec to Kite features.

| # | Category | Bar | Kite implementation |
|---|----------|-----|---------------------|
| 1 | Verifiability | Antigravity | `VerificationCollector` → `artifact` events; diffs, test commands, verification status on submit |
| 2 | Graduated autonomy | Codex CLI | `auto` / `trust` / `approve` / `readonly`; sandbox on by default; `trusted_paths` in guardrails |
| 3 | Transparent context | Warp | Exact `$ command` rows; `secrets_redacted` count in tool output |
| 4 | Parallel + legible | Claude/Antigravity | `task` tool `prompts[]` parallel fan-out; Warp-style command blocks with exit/duration |
| 5 | Model-agnostic | OpenCode | LiteLLM + Ollama catalog; `kite import <format>` for Cursor/Claude/Aider/Codex sessions |
| 6 | MCP-native | Claude Code | `[[mcp]]` servers in TOML → stdio JSON-RPC → `mcp_<server>_<tool>` registry |
| 7 | Long-horizon context | Claude Code | Auto-compaction, sessions/resume, image token budgeting in `estimate_message_tokens` |
| 8 | Cloud/local parity | Codex CLI | `kite cloud list|apply`, `kite apply <trajectory>` |
| 9 | Terminal-native | Aider/Warp | `kite run`, `kite exec`, `--json`, `--stdin`, exit codes |
| 10 | GitHub integration | Copilot | `gh_issue`, `gh_pr`, `gh_prs`, `gh_runs`, `gh_run` tools (via `gh` CLI) |
| 11 | Governance/audit | Cline/OpenHands | `~/.kite/audit.jsonl`; `kite audit`; approval trail |
| 12 | Multi-agent roles | Roo Code | `--role architect|implementer|debugger` + role prompt fragments |
| 13 | Predictable cost | — | Pre-flight `cost_estimate` event; 80% `cost_warning`; footer meter |
| 14 | Honest limits | — | Loop warnings, verification gaps, unverified submit banner |

## Commands

```bash
kite run --approval trust --role debugger "why does login fail?"
kite exec --json "add a unit test for parse_role"
kite import cursor ~/.cursor/sessions/export.json
kite apply ~/.kite/trajectories/<session>.json
kite cloud apply <task-id>
kite audit --json
```

## Config (`~/.kite/configs/default.toml`)

- `[github] enabled = true`
- `[[mcp]]` server blocks
- `[guardrails] trusted_paths = ["src/"]`
- `[agent] role = "auto"`
