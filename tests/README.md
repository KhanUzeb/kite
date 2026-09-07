# Tests

Run from the repo root after installing Kite:

```bash
./scripts/install.sh          # macOS/Linux — or .\scripts\install.ps1 on Windows
pytest
./scripts/install.sh --no-clone --verify   # install + smoke check
```

Or manual install: `uv venv --python 3.12` → activate → `uv pip install -e ".[dev]"` → `pytest`.

## CI

GitHub Actions runs `pytest` on **every push and pull request to `main`** (Python 3.11 + 3.12). See [CONTRIBUTING.md](../CONTRIBUTING.md#ci-github-actions).

## Layout

| File | Covers |
|------|--------|
| `test_guardrails.py` | sandbox, path escape, secret redaction |
| `test_approval.py` | trust mode, `trusted_paths` bash skip |
| `test_loop_guard.py` | repetitive tool detection |
| `test_session.py` | append-only JSONL, meta `updated_at` |
| `test_verification.py` | test-command artifact detection |
| `test_orchestrator.py` | parallel subagent dispatch |
| `test_context_cache.py` | 30s project-context TTL |
| `test_skills_cache.py` | 45s skills TTL |
| `test_status.py` | context meter, footer tail |
| `test_chips.py` | tool chips, task row badges |
| `test_animations.py` | loader glyphs, elapsed format |
| `test_render.py` | warning events, git-stat `+N,-M` on edit (ANSI-safe) |
| `test_preview_diff.py` | approval previews, `+125,-21` counts |
| `test_skill_install.py` | npm/npx/git/local-path parse; global symlink/junction; project `.kite/skills` link |
| `test_application_contracts.py` | RunSpec, EventEnvelope, ApplicationRunService |
| `test_context_assembler.py` | budgets, untrusted delimiters, inspection redaction |
| `test_harness_universal.py` | 0.9 adapters: policy, approval, verification, replay, reducer |
| `test_sota_harness.py` | submit tool, repomap, EvidenceVerifier, ToolExecutor loop, replay acceptance |
| `test_ui_busy.py` | busy composer, approval polling, verification_status footer |
| `test_submit_gate.py` | submit blocked without evidence |
| `test_policy_execution.py` | PolicyEngine, ToolExecutor, ChangeJournal, path policy |
| `test_persistence.py` | SQLite event store, resume, redaction |
| `test_model_gateway.py` | retries, BudgetLedger |
| `test_replay.py` | recorded replay without live providers |
| `test_theme.py` | `/theme` palettes, `/font` glyphs |
| `test_config.py` | default runtime TOML load |
| `test_reasoning.py` | `/reasoning` levels, effort detection, completion |
| `test_setup.py` | `kite setup` / `kite keys` env writer |
| `test_maintainer_dashboard.py` | maintainer-only dashboard gate |
| `test_git.py` | git checkpoints, `/undo` |
| `test_prompts.py` | prompt assembly, greeting handling |
| `test_session_list.py` | session list/delete |
| `test_cache.py` | prompt cache stats |
| `test_context_checkpoint_handoff.py` | checkpoints, handoff export, compaction facts |
| `test_bench.py` | Harness timing suite + budget regression (`kite bench --check`) |
| `test_tool_result.py` | ToolResult contract, tool metadata |
| `test_workspace.py` | execution cwd, host/restricted mode, `set_cwd` |
| `test_cancellation_parallel.py` | bash cancel, parallel read tools |
| `test_repl_lazy.py` | REPL cold start skips model resolve |
| `test_cli_commands.py` | slash legacy aliases, `kite help` |

Fixtures in `conftest.py`: isolated `KITE_HOME`, sample workspace with `src/`, `strip_ansi()` helper.

Not covered yet: live LLM calls, catalog resolve edge cases, full CLI integration, handoff round-trip across machines.
