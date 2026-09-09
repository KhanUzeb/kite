# Contributing to Kite

Thanks for considering a contribution. Kite is a slim, hackable coding-agent harness, and the design goal is that every layer stays readable in one sitting. Keep that in mind when you open a PR.

## How to set up

```bash
git clone https://github.com/KhanUzeb/kite.git
cd kite
./scripts/install.sh --dev      # editable .venv (or plain ./scripts/install.sh in a checkout)
# .\scripts\install.ps1 -Dev    # Windows PowerShell
```

End users (global CLI, any project dir): `curl …/install.sh | bash` or `irm …/install.ps1 | iex` — see README. That path uses `uv tool install`, not a local clone.

`--dev` creates a venv, installs Kite in editable mode, seeds `~/.kite/.env` from `.env.example` when missing, and bootstraps `~/.kite/`. Use `./scripts/install.sh --dev --verify` to run pytest after install.

Package maintenance (not `kite` CLI subcommands):

```bash
./scripts/pkg.sh update       # uv tool upgrade, or git pull + editable reinstall
./scripts/pkg.sh reinstall
./scripts/pkg.sh uninstall    # --global or --remove-venv as needed
```

Windows: `.\scripts\pkg.ps1 update|reinstall|uninstall`

Then run the suite (or the CI-parity script):

```bash
./scripts/lint.sh    # sync_version + ruff + pytest + kite bench --check
pytest
pytest -v
```

## CI (GitHub Actions)

Workflow: [`.github/workflows/tests.yml`](.github/workflows/tests.yml)

| Trigger | Checks |
|---------|--------|
| **Push** or **pull request** to `main` | pytest on **Linux and Windows** × Python 3.11 and 3.12 (includes `test_security_*`, `test_guardrails.py`); `ruff check src tests`; `python scripts/sync_version.py --check`; `kite bench --check` |
| **Actions → Tests → Run workflow** | manual re-run anytime |

CI sets `KITE_HOME` to an isolated temp directory and `KITE_SKIP_SETUP=1` so tests never prompt for onboarding.

Always run `./scripts/lint.sh` (or `pytest` + `ruff check src tests` + `kite bench --check`) locally before opening a PR.

## Ways to contribute

- **Documentation** — `README.md`, `CONTEXT.md`, `AGENTS.md`, `docs/` (including [docs/memory.md](docs/memory.md)), `kite_commands.md`, and bundled prompts (`src/kite/data/prompts/`, `data/commands/`) are the sources of truth. The design docs are generated into PDFs (`uv pip install fpdf2 && python scripts/build_design_pdf.py`) but the markdown is what we edit.
- **Skills** — drop a `SKILL.md` into `src/kite/data/skills/` or install packs via `kite skills --add <npm|npx|owner/repo>`.
- **Tools / providers** — `tools/`, `providers/`, and `models/` are the extension points. Custom tools: `Harness.extra_tools` or `.kite/extensions/*.py` via `ExtensionAPI.register_tool`.
- **Bug fixes** — add or extend a test in `tests/`.

## Before you open a PR

1. Run `pytest` and make sure it's green.
2. Keep the architecture boundaries: CLI/UI subscribe to events; `ApplicationRunService` (0.9) or `AgentRuntime` assembles; the agent loops. Don't reach across layers.
3. Prefer data-driven changes (TOML/Markdown) over new Python constants.
4. Update the relevant doc if behavior changes — especially `kite_commands.md`, `CONTEXT.md` (new terms), `docs/memory.md`, `SECURITY.md` (trust boundaries), `architecture.md` (layer changes), `docs/kite-system-design.md`, or `src/kite/data/prompts/system.md` (agent instructions).

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
