# Changelog

All notable changes to Kite are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
