# Contributing to Kite

Thanks for considering a contribution. Kite is a slim, hackable coding-agent harness, and the design goal is that every layer stays readable in one sitting. Keep that in mind when you open a PR.

## How to set up

```bash
git clone https://github.com/KhanUzeb/kite.git
cd kite
./scripts/install.sh --dev --local  # editable .venv, no global CLI/shell-profile changes
# .\scripts\install.ps1 -Dev -Local  # Windows PowerShell
```

End users (global CLI, any project dir): `curl …/install.sh | bash` or `irm …/install.ps1 | iex` — see README. That path uses `uv tool install`, not a local clone.

`--dev` creates a venv and also replaces the global editable CLI; add `--local` for isolated work. Local-only installs default `KITE_HOME` to `.venv/kite-home` unless explicitly supplied. Both paths seed a missing `.env` from `.env.example` and bootstrap that home. Use `--verify` to run all CI gates after install. Activate `.venv` before invoking `kite` or `pytest`.

Development installs on both platforms use the committed `uv.lock` with `uv sync --frozen --extra dev`; warm installs reuse the environment rather than resolving dependencies again.

Update / uninstall the global CLI with uv:

```bash
uv tool upgrade kite
uv tool uninstall kite
```

Then run the suite (same gates as CI):

```bash
./scripts/ci_check.sh          # macOS/Linux
# .\scripts\ci_check.ps1       # Windows
```

Or the same commands by hand:

```bash
python scripts/sync_version.py --check
ruff check src tests scripts
pytest -q
kite bench --check
```

### Fast, isolated agent loops

```bash
./scripts/worktree.sh render-fix          # sibling checkout + private .venv and Kite home
./scripts/ci_check.sh --fast              # staged/unstaged/untracked changes against HEAD
./scripts/ci_check.sh --fast --base main  # include branch changes against a revision
./scripts/ci_check.sh --fast --files src/kite/ui/render.py
python scripts/ci_fast.py --list          # inspect the selected files without running gates
```

Worktrees start at **committed HEAD**; uncommitted edits are not copied. The setup script prints activation/home exports and gate commands, and never repoints the global CLI. Reusing a name fails rather than overwriting work. `uv` must be installed; package downloads are needed on a cold cache. Re-running `install.sh --dev --local` reuses the venv (and refreshes the editable package).

Fast mode always checks version stamps and the quick benchmark budgets. Ruff sees changed Python files; pytest uses broad domain mappings. Shared configuration, unknown domains, deleted tests, and script changes fall back to the full suite. Documentation-only changes skip pytest. This is a feedback loop, **not proof of unaffected behavior**: run full gates before merging. A fresh temporary `KITE_HOME` is cleaned up after a gate run unless you explicitly provide one. No xdist dependency is required or assumed.

### Performance evidence

See [`kite bench`](kite_commands.md#harness-timing-kite-bench) for quick/full workloads, `--save` / `--compare`, noise thresholds, and measurement limits.

### Offline end-to-end QA and debugging

```bash
python scripts/e2e_smoke.py --output /tmp/kite-smoke
# Windows: python scripts/e2e_smoke.py --headless-only --output C:/Temp/kite-smoke
python scripts/profile_cli.py --output /tmp/kite.pstats -- bench --suite full
python -m pstats /tmp/kite.pstats
```

The smoke runner invokes the real CLI and LiteLLM against a recorded OpenAI-compatible server bound to loopback; it never needs real provider credentials or external networking. A subprocess-only Python audit hook rejects external socket connections/DNS; `KITE_OFFLINE=1` disables update checks. Headless QA edits a file, runs its syntax verification, and requires `Submitted`. POSIX PTYs exercise startup, `/help`, and `/quit` at 50/80/120 columns under both `TERM=xterm-256color` and `TERM=dumb`, in a Unicode workspace. Raw `.ansi` and cleaned `.txt` terminal **transcripts** are review artifacts, not a pixel-perfect terminal emulator or an automatic wrapping/accessibility audit.

Artifacts include headless stdout JSON, stderr event logs, trajectory JSON, session JSONL and provider requests. They use generated content; treat real-run trajectories/sessions as sensitive. For real tasks, `kite run --headless --verbose --output trajectory.json ...` exposes stream/tool logs on stderr and the existing session store lives under `$KITE_HOME/sessions`. `profile_cli.py` accepts any Kite CLI invocation after `--`, writes cProfile statistics even on a CLI failure, uses an isolated home by default, and profiles the main thread only (not worker threads/subprocess CPU). `ReplayBundle` is a model-response/acceptance replay helper, not a substitute for driving CLI/tool execution.

For live event diagnostics, see [`KITE_TRACE_JSONL`](kite_commands.md#runtime-event-tracing).


## CI (GitHub Actions)

Workflow: [`.github/workflows/tests.yml`](.github/workflows/tests.yml)

| Trigger | Checks |
|---------|--------|
| **Push** or **pull request** to `main` | pytest on **Linux (Python 3.11/3.12) and Windows (3.12)**; hermetic pytest on Linux with fail-loud provider CLI shims; `ruff check src tests scripts`; version stamps; quick benchmark budgets; offline CLI smoke (headless everywhere, PTYs on Linux), with saved QA artifacts |
| **Actions → Tests → Run workflow** | manual re-run anytime |

CI sets `KITE_HOME` to an isolated temp directory, `KITE_SKIP_SETUP=1` so tests never prompt for onboarding, and `KITE_TYPED_PICK=1` so model/session pickers stay on the scripted prompt (no TTY overlay).

Always run full `scripts/ci_check.sh` and the offline smoke runner locally before opening a PR.

## Ways to contribute

- **Documentation** — `README.md`, `CONTEXT.md`, `AGENTS.md`, `architecture.md`, `kite_commands.md`, current `docs/RELEASE-*.md`, and bundled prompts (`src/kite/data/prompts/`, `data/commands/`) are the sources of truth. Edit the markdown; do not add PDF generator scripts.
- **Skills** — drop a `SKILL.md` into `src/kite/data/skills/` or install packs via `kite skills --add <npm|npx|owner/repo>`.
- **Tools / providers** — `tools/`, `providers/`, and `models/` are the extension points. Custom tools: `Harness.extra_tools` or `.kite/extensions/*.py` via `kite.plugins.extensions.ExtensionAPI.register_tool`.
- **Bug fixes** — add a named behavioral regression test in the matching domain module; follow the [test policy](AGENTS.md#tests--ci), not a collection-count target.

## Before you open a PR

1. Run `pytest` and make sure it's green.
2. Keep the architecture boundaries: CLI/UI subscribe to events; `ApplicationRunService` (0.9) or `AgentRuntime` assembles; the agent loops. Don't reach across layers.
3. Prefer data-driven changes (TOML/Markdown) over new Python constants.
4. Update the relevant doc if behavior changes — especially `kite_commands.md`, `CONTEXT.md` (new terms, including memory layers), `SECURITY.md` (trust boundaries), `architecture.md` (layer changes), or `src/kite/data/prompts/system.md` (agent instructions).

## Commit style

Short, conventional-ish commits read well here:

```
feat(ui): add /theme palette switching
fix(guardrails): block ssh key reads outside sandbox
docs: refresh module map
```

## Code of conduct

Be respectful. Assume good intent. Keep discussion about the code, not the person.

## Releasing

Maintainers only: after merging a release batch, run `./scripts/bump_release.sh X.Y.Z` (updates `pyproject.toml`, `src/kite/__init__.py`, and `CHANGELOG.md`), tag `vX.Y.Z`, and publish release notes.

Manual alternative: bump version in `pyproject.toml` and `src/kite/__init__.py`, edit `CHANGELOG.md`, tag `vX.Y.Z`.

Private maintainer dashboard (not in public docs): set `KITE_MAINTAINER_KEY` in `~/.kite/.env`, then run `kite maintainer dashboard`.
