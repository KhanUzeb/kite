# Tests

Run from the repo root after installing Kite:

```bash
./scripts/install.sh          # macOS/Linux — or .\scripts\install.ps1 on Windows
pytest
./scripts/install.sh --dev --verify   # install + smoke check
```

Or: `uv pip install -e ".[dev]"` → `pytest`. No live LLM calls. `conftest.py` isolates `KITE_HOME`.

## CI

`.github/workflows/tests.yml` runs pytest on Linux and Windows × Python 3.11 and 3.12, plus `ruff check src tests`, `sync_version.py --check`, and `kite bench --check`.

## Layout (~150 collected tests)

Prefer one module per domain. Combine related asserts in a single test (or a loop) instead of one-assert functions. Do not use `@pytest.mark.parametrize` just to inflate the collect count.

| File | Covers |
|------|--------|
| `test_security.py` | sandbox, SSRF, env filter, redaction, inspection bash, nested-agent bounds |
| `test_guardrails.py` | dangerous bash, cache deletes, skill-tree reads |
| `test_approval.py` | supervised/auto/yolo, mandatory high-risk, non-interactive deny |
| `test_agent.py` | loop limits/retry/guard, modes, completion, cancel, dispatch, submit gate |
| `test_application.py` | RunSpec, PolicyEngine, ToolExecutor, verification, nested policy |
| `test_providers.py` | BYOS OAuth, select, reasoning, Codex LiteLLM flatten |
| `test_credentials.py` | `~/.kite/.env` keys, web-tool keys, Claude usable vs linked |
| `test_cli.py` | apply/diff, slash help, chat/resume flags |
| `test_headless_tasks.py` | JSONL tasks, Submitted-only success, non-interactive approval |
| `test_ui.py` | render, theme, REPL slash/jobs, attach, preview |
| `test_composer.py` | Ctrl-C steer/stop, queue, approval composer |
| `test_memory.py` | persistence modes, continuity, USER/PROFILE, prompts |
| `test_session.py` | append-only JSONL, compact rewrite, stats |
| `test_tools.py` | paid web chain, jobs, compaction, shell |
| `test_web.py` | search/fetch/crawl parsing (no network) |
| `test_orchestrator.py` | crew dispatch, success semantics |
| `test_workspace.py` | host vs restricted, `set_cwd` |
| `test_util.py` | cache, version stamps, venv, replay, tool metadata |
| `test_skills.py` | install specs, user vs project load |
| `test_bench.py` | harness timing budgets (`kite bench --check`) |

Fixtures: isolated `KITE_HOME`, sample workspace with `src/`, `strip_ansi()`.

Imports use flattened modules: `kite.application.execution`, `kite.application.policy`, `kite.eval`, `kite.tasks`, `kite.plugins.extensions` (not nested `….pipeline` / `….headless` / `….replay` packages).
