"""Short CLI help — grouped quick reference for `kite help` and `--help` epilog."""

from __future__ import annotations

CLI_EPILOG = """quick start:
  kite setup              API key + model wizard
  kite                    interactive REPL (same as kite chat)
  kite run "task"         one-shot task

common:
  kite sessions           list transcripts
  kite resume <id>        continue a session
  kite models -p groq     list models
  kite bench              harness timing (no LLM)

run `kite help` for the full map  ·  in REPL type /help
"""


def cli_help_text() -> str:
    return """Kite CLI — quick reference

Session
  kite | kite chat              REPL (plan/build, /slash commands)
  kite run "task"               one-shot
  kite resume <id> [message]    continue session
  kite sessions [--show id]     list or inspect transcripts

Setup & model
  kite setup                    first-run wizard
  kite keys [--set provider]    API keys (~/.kite/.env)
  kite providers                credential status
  kite models -p groq [--select]
  kite config [--select-model]

Project
  kite context                  preview workspace discovery
  kite skills [--show name] [--add pkg]
  kite commands | kite plugins
  kite memory [--remember text]

Advanced
  kite runtime-config           merged agent TOML
  kite bench [--json] [--compare file]
  kite apply | kite import | kite exec | kite audit | kite cloud

REPL essentials (type /help in chat)
  /plan /build                  read-only vs apply
  /model [list|select|groq/id]  model picker
  /login /keys /select          credentials
  /checkpoint /handoff /compact session continuity
  /session list | /resume <id>  transcripts
  /status                       mode, model, cost

Flags on run/chat/resume: -p provider  -m model  --cwd PATH  --mode plan|build
  --approval auto|approve|trust|readonly  -v  -q  --attach PATH

Docs: kite_commands.md
"""
