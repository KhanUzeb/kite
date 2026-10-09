# Tests

Run from the repo root after installing Kite:

```bash
./scripts/install.sh --dev --local  # macOS/Linux; activate .venv before pytest
pytest
./scripts/install.sh --dev --verify   # install + smoke check
```

Or: `uv pip install -e ".[dev]"` → `pytest`. No live LLM calls. `conftest.py` isolates `KITE_HOME`.

## CI

`.github/workflows/tests.yml` runs pytest on Linux (Python 3.11/3.12) and Windows (3.12), plus `ruff check src tests scripts`, `sync_version.py --check`, and `kite bench --check`. Env: `KITE_HOME`, `KITE_SKIP_SETUP=1`, `KITE_TYPED_PICK=1`. Locally: `./scripts/ci_check.sh` or `.\scripts\ci_check.ps1`.

## Agent feedback loops

See [AGENTS.md — Tests & CI](../AGENTS.md#tests--ci) for the dev loop and test policy.

Benchmark serialization/comparison tests use synthetic reports, not a second full timing run. Only the budget test measures the quick suite.

## Layout

Prefer one module per domain; follow the [named-test and runtime-budget policy](../AGENTS.md#tests--ci). Do not use `@pytest.mark.parametrize` just to inflate the collect count.

| File | Covers |
|------|--------|
| `test_security.py` | sandbox, SSRF, env filter, redaction, inspection bash, nested-agent bounds |
| `test_guardrails.py` | dangerous bash, cache deletes, skill-tree reads |
| `test_approval.py` | supervised/auto/yolo, mandatory high-risk, non-interactive deny |
| `test_agent.py` | loop limits/retry/guard, modes, completion, cancel, dispatch, submit gate |
| `test_application.py` | RunSpec, PolicyEngine, ToolExecutor, verification, nested policy |
| `test_providers.py` | credentials, OAuth, model selection, capabilities, reasoning, web-tool keys |
| `test_cli.py` | apply/diff, slash help, chat/resume flags, numbered pickers |
| `test_headless_tasks.py` | JSONL tasks, Submitted-only success, non-interactive approval |
| `test_ui.py` | render, theme, REPL slash/jobs, attach, preview |
| `test_composer.py` | Ctrl-C steer/stop, queue, approval composer, steer-keeps-composer, inbox fallback |
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

An autouse fixture blocks external `socket.connect`, `socket.connect_ex`, and `socket.create_connection` calls before they reach the network. Loopback TCP and Unix sockets remain available for local integration tests. Mock HTTP and DNS in web tests; do not rely on provider keys being absent from the parent environment. Credential tests must register environment restoration before code that writes directly to `os.environ` (`monkeypatch.delenv` alone does not track an already-absent key).

Imports use flattened modules: `kite.application.execution`, `kite.application.policy`, `kite.eval`, `kite.tasks`, `kite.plugins.extensions` (not nested `….pipeline` / `….headless` / `….replay` packages).
