# Tests

Run from the repo root:

```bash
uv pip install -e ".[dev]"
pytest
```

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
| `test_render.py` | warning event rendering |
| `test_config.py` | default runtime TOML load |

Fixtures in `conftest.py`: isolated `KITE_HOME`, sample workspace with `src/`.

Not covered yet: live LLM calls, catalog resolve edge cases, compaction invariants, full CLI integration.
