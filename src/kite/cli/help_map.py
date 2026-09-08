"""Short CLI help — grouped quick reference for `kite help` and `--help` epilog."""

from __future__ import annotations

CLI_EPILOG = """quick start:
  kite setup              API key + model wizard
  kite                    interactive REPL (same as kite chat)
  kite run "task"         one-shot task

common:
  kite sessions           pick a transcript (or --show / --delete)
  kite resume [id]        continue a session (omit id to pick)
  kite models [-p groq]   pick a live model (--list to dump)
  kite bench              harness timing (no LLM)

run `kite help` for the full map  ·  in REPL type /help
"""


def cli_help_text() -> str:
    return """Kite CLI - quick reference

Session
  kite | kite chat              REPL (plan/build, /slash commands)
  kite run "task"               one-shot
  kite resume [id] [message]    continue session (omit id to pick)
  kite sessions                 pick a transcript to open / show / delete

Setup & model
  kite setup                    first-run wizard
  kite keys [--set [provider]]  API keys - TTY pick to link
  kite providers                status, then pick to connect
  kite models [-p groq]         pick a model (--list to dump)
  kite config [--select-model] [--session-persistence full|redacted|disabled]
  kite privacy                  security policy summary

Project
  kite context                  preview workspace discovery
  kite skills [--show name] [--add pkg|path]
  kite commands | kite plugins
  kite memory [--remember text]

Advanced
  kite runtime-config           merged agent TOML
  kite bench [--json] [--compare file]
  kite apply | kite import | kite exec | kite audit | kite cloud

REPL essentials (type /help in chat)
  /plan /build                  checklist-only vs apply
  /model [list|select|groq/id]  model picker
  /login /keys /select          credentials
  /checkpoint /handoff /compact session continuity
  /session list | /resume <id>  transcripts
  /status                       mode, model, cost, session persistence
  /privacy                      security policy; /privacy sessions …
  /stop /steer                  stop turn or redirect (session stays)
  /jobs /kill [id|all]          background bash + live subagents

Flags on run/chat/resume: -p provider  -m model  --cwd PATH  --mode plan|build
  --approval auto|approve|supervised|yolo|trust|readonly  --auto-compact  -v  -q  --attach PATH

Docs: kite_commands.md
"""
