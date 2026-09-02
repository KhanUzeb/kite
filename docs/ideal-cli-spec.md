# Ideal CLI spec coverage (Kite 0.8.2)

How Kite maps onto the 14-category Ideal Coding CLI spec.

| # | Category | Bar | Kite implementation |
|---|----------|-----|---------------------|
| 1 | Verifiability | Antigravity | `VerificationCollector` -> `artifact` events; diffs, test commands, verification status on submit |
| 2 | Graduated autonomy | Codex CLI | `auto` / `trust` / `approve` / `readonly`; sandbox on by default; **`trusted_paths`** relaxes trust-mode bash inside subtrees |
| 3 | Transparent context | Warp | Exact `$ command` rows; `secrets_redacted` count in tool output |
| 4 | Parallel + legible | Claude/Antigravity | `task` tool `prompts[]` parallel fan-out; **`subagent`** LLM orchestrator with manager events |
| 5 | Model-agnostic | OpenCode | LiteLLM + Ollama catalog; `kite import <format>` for Cursor/Claude/Aider/Codex sessions |
| 6 | Custom tools | Kite | `Harness.extra_tools`, `.kite/extensions/` via `ExtensionAPI.register_tool` |
| 7 | Long-horizon context | Claude Code | Preserved-fact compaction; auto-checkpoint ~72%; `/checkpoint` + `/handoff`; sessions/resume; image token budgeting |
| 8 | Cloud/local parity | Codex CLI | `kite cloud list|apply`, `kite apply <trajectory>` |
| 9 | Terminal-native | Aider/Warp | `kite run`, `kite exec`, `--json`, `--stdin`, exit codes |
| 10 | GitHub integration | Copilot | `gh_issue`, `gh_pr`, `gh_prs`, `gh_runs`, `gh_run` tools (via `gh` CLI) |
| 11 | Governance/audit | Cline/OpenHands | `~/.kite/audit.jsonl`; `kite audit`; approval trail |
| 12 | Multi-agent roles | Roo Code | `--role architect|implementer|debugger` + role prompt fragments |
| 13 | Predictable cost | — | Pre-flight `cost_estimate` event; 80% `cost_warning`; footer meter; **`cache_hit`** ratio (pi-style prefix cache) |
| 14 | Honest limits | — | Loop warnings, verification gaps, unverified submit banner |

## Install

**Any workstation**: clone and run the install script (creates `.venv`, editable install, seeds `~/.kite/.env`):

```bash
git clone https://github.com/KhanUzeb/kite.git && cd kite && ./scripts/install.sh
# Windows: .\scripts\install.ps1
```

One-liner: `curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash`

**Any project**: after install, activate the venv and run `kite` from whatever repo you are working in. Workspace defaults to the shell cwd; use `--cwd` on `run` / `chat` / `resume` / `context` / `skills` / `memory` to target another tree. Config and sessions are global (`~/.kite/`); optional per-repo overlays live in `<repo>/.kite/`.

See [README.md](../README.md#use-kite-on-any-project-not-just-this-repo) for PATH setup and examples.

## Testing

```bash
./scripts/install.sh          # or: uv pip install -e ".[dev]"
pytest
```

**CI:** `.github/workflows/tests.yml` runs the full suite on every push and pull request to `main` (Python 3.11 + 3.12). Maintainers can re-run from the Actions tab.

Unit tests in `tests/` cover guardrails, `trusted_paths` approval, loop guard, session append, verification heuristics, orchestrator dispatch, context/skills caches, git-stat diffs, skill install, reasoning/setup UX, and UI helpers.

## Commands

```bash
kite run --approval trust --role debugger "why does login fail?"
kite exec --json "add a unit test for parse_role"
kite import cursor ~/.cursor/sessions/export.json
kite apply ~/.kite/trajectories/<session>.json
kite cloud apply <task-id>
kite audit --json
kite run  # footer shows cache hit % when provider returns cached tokens
```

## Orchestrator

The `subagent` tool spawns bounded nested agent runs (default: 10 steps, $1 budget each).
Pass multiple `prompts` for parallel workers, and the TUI shows `▸ subagent` / `✓ subagent` rows.

```toml
[orchestrator]
max_workers = 3
step_limit = 10
cost_limit = 1.0
```

## Prompt cache

Pi-style prefix caching: the stable system prompt gets `cache_control` breakpoints on Anthropic.
OpenAI cached_tokens and Anthropic cache_read are tracked and shown in the footer.

```toml
[cache]
enabled = true
```

## UI loaders

Terminal loaders inspired by [beautifului.dev](https://www.beautifului.dev/) (TTY-only subset):

```bash
KITE_LOADER=grid   # default, pixel strip + shimmer + elapsed time
KITE_LOADER=dots   # dot chase
```

```toml
[ui]
loader = "grid"
```

## Config (`~/.kite/configs/default.toml`)

- `[github] enabled = true`
- `[guardrails] trusted_paths = ["src/"]`
- `[agent] role = "auto"`
