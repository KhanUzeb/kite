# Changelog

All notable changes to Kite are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.7] - 2026-08-30

### Added
- `kite setup` and `kite keys` onboarding with hidden API key input to `~/.kite/.env`.
- REPL `/login`, `/logout`, `/keys`, and `/select` for credentials and model selection.
- Keyboard shortcuts: Ctrl+O expand tools, Ctrl+P plan, Ctrl+B build, Ctrl+S status.
- `/thinking` and `/fast` level menus when the provider advertises both effort modes.
- Maintainer-only `kite maintainer dashboard` (requires `KITE_MAINTAINER_KEY`).
- `CONTEXT.md` and `AGENTS.md` for agent-readable repo guidance.
- CI workflow: pytest on push/PR batches with 5+ commits.

### Changed
- Nemotron and other reasoning models detected via name heuristic when API metadata is empty.
- Project context discovery loads `CONTEXT.md` alongside `AGENTS.md`.

## [0.6.6] - 2026-08-30

### Added
- Skill packs: install from npm, npx, or GitHub `owner/repo` into `~/.kite/skills` (`kite skills --add`, `skills/install.py`).
- UI themes and fonts: `/theme` (auto, kite, dark, light, dim, mono) and `/font` (unicode, ascii), persisted in `~/.kite`.
- Git-stat `+N,-M` counts shown on write/edit diffs and the plan checklist.

### Changed
- Lazy CLI imports for a cheaper REPL cold start.
- Provider catalog and runtime config now support user overlays.
- `kite run` accepts `--cwd` to target a directory other than the shell's working directory.

## [0.6.5] - 2026-08-29

### Added
- Initial public-facing harness: mini-swe-agent loop, tau-style tools/providers/skills/guardrails, Rich TUI, sessions, and memory.
- Multi-provider model resolution via LiteLLM (OpenAI, Anthropic, Groq, OpenCode Zen/Go, NVIDIA NIM, Ollama, and more).
- Approval modes (`auto` / `approve` / `trust` / `readonly`) and plan/build modes.
- MCP stdio client, subagent orchestrator, and trajectory import from Cursor/Claude/Aider/Codex.
