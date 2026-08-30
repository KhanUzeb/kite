# Tests

Run from the repo root after installing Kite:

```bash
./scripts/install.sh          # macOS/Linux — or .\scripts\install.ps1 on Windows
pytest
```

Or manual install: `uv venv --python 3.12` → activate → `uv pip install -e ".[dev]"` → `pytest`.

## CI

GitHub Actions runs `pytest` on **push/PR to `main` when the batch has 5+ commits**. Smaller pushes skip automatically; use **Actions → Tests → Run workflow** to force a run. See [CONTRIBUTING.md](../CONTRIBUTING.md#ci-github-actions).

## Layout

| File | Covers |
|------|--------|
| `test_guardrails.py` | sandbox, path escape, secret redaction |
| `test_approval.py` | trust mode, `trusted_paths` bash skip |
| `test_loop_guard.py` | repetitive tool detection |
| `test_session.py` | append-only JSONL, meta `updated_at` |
| `test_verification.py` | test-command artifact detection |
| `test_mcp.py` | MCP startup warnings |
| `test_orchestrator.py` | parallel subagent dispatch |
| `test_context_cache.py` | 30s project-context TTL |
| `test_skills_cache.py` | 45s skills TTL |
| `test_status.py` | context meter, footer tail |
| `test_chips.py` | tool chips, task row badges |
| `test_animations.py` | loader glyphs, elapsed format |
| `test_render.py` | warning events, git-stat `+N,-M` on edit |
| `test_preview_diff.py` | approval previews, `+125,-21` counts |
| `test_skill_install.py` | npm/npx/git spec parse, user-skill `~` mark |
| `test_theme.py` | `/theme` palettes, `/font` glyphs |
| `test_config.py` | default runtime TOML load |
| `test_reasoning.py` | `/thinking` `/fast` levels, effort detection |
| `test_setup.py` | `kite setup` / `kite keys` env writer |
| `test_maintainer_dashboard.py` | maintainer-only dashboard gate |
| `test_git.py` | git checkpoints, `/undo` |
| `test_prompts.py` | prompt assembly, greeting handling |
| `test_session_list.py` | session list/delete |
| `test_cache.py` | prompt cache stats |
| `test_cli_import.py` | session import formats |

Fixtures in `conftest.py`: isolated `KITE_HOME`, sample workspace with `src/`.

Not covered yet: live LLM calls, catalog resolve edge cases, compaction invariants, full CLI integration.
