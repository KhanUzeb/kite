"""CLI help — Codex/Pi-style grouped map. Every shipped command is listed."""

from __future__ import annotations

# Compatibility aliases stay registered; they remain in --help so they are usable.
CLI_HIDDEN_ALIASES: frozenset[str] = frozenset()

# Every argparse subcommand except maintainer (gated).
CLI_COMMANDS: frozenset[str] = frozenset({
    "help",
    "run",
    "chat",
    "resume",
    "sessions",
    "providers",
    "setup",
    "login",
    "logout",
    "keys",
    "web-keys",
    "models",
    "config",
    "privacy",
    "context",
    "init",
    "skills",
    "commands",
    "plugins",
    "memory",
    "runtime-config",
    "apply",
    "import",
    "exec",
    "audit",
    "dashboard",
    "cloud",
    "bench",
    "tasks",
    "subagents",
    "maintainer",
    "update",
    "uninstall",
    "gh",
})

# Shown first in `kite --help` (full list still appears below).
CLI_PRIMARY_COMMANDS: frozenset[str] = CLI_COMMANDS - frozenset({"maintainer"})


def docs_help() -> str:
    from kite import __version__

    return (
        "docs\n"
        "  kite_commands.md   CLI and slash map\n"
        "  CONTEXT.md         terms, including memory layers\n"
        "  architecture.md    layers and extension points\n"
        "  SECURITY.md        trust boundaries\n"
        f"  docs/RELEASE-{__version__}.md  current release notes\n"
    )


CLI_EPILOG = """
session
  kite [prompt]        interactive session (optional opening task)
  kite chat [prompt]   same as bare kite
  kite run "task"      one-shot (CI: --headless --json)
  kite --print "task"  one-shot, final answer only (Pi -p)
  kite exec "task"     CI alias for run (auto, quiet)
  kite resume [id]     continue a session (--last)
  kite sessions        list / show / delete transcripts

self-manage
  kite update [--check]   upgrade the installed CLI (uv tool)
  kite uninstall [-y]     remove the CLI (keeps ~/.kite data; --purge deletes it)

setup
  kite setup | login | logout | keys | web-keys | providers | models
  kite config | privacy

project
  kite init [dir] [--chat|--force]   scaffold AGENTS.md (agents.md standard)
  kite context | skills | commands | plugins | memory | subagents
  kite gh issue view|list|create|comment  ·  kite gh pr view|list|create  ·  kite gh auth

ops
  kite tasks | bench | apply | import | audit | dashboard | cloud | runtime-config

unknown first word is treated as a prompt (Codex/Pi).  kite help  ·  /help
"""


def cli_help_brief() -> str:
    return """Kite CLI

  kite [prompt]              lean interactive session
  kite run "task"            one-shot / headless
  kite resume [id]           continue work
  kite setup                 onboarding
  kite sessions              history
  kite tasks                 batches
  kite models | keys | config | skills | …

  kite --help                every subcommand
  kite help all              this map plus flags
  kite update | uninstall    upgrade / remove the installed CLI
  REPL: /help  ·  /help all
"""


def cli_help_text() -> str:
    return """Kite CLI - full reference

Session
  kite | kite chat [prompt]     lean REPL (plan/build, /slash commands)
  kite run "task"               one-shot
  kite --print "task"           one-shot, final answer on stdout only (Pi -p)
  kite resume [id] [message]    continue session (omit id to pick)
  kite sessions                 pick a transcript to open / show / delete

Self-manage
  kite update [--check]         upgrade the installed CLI (uv tool)
  kite uninstall [-y] [--purge] remove the CLI (keeps ~/.kite data unless --purge)

Setup & model
  kite setup                    first-run wizard
  kite login [provider]         BYOK key or BYOS OAuth
  kite logout [provider]        unlink BYOS
  kite keys [--set [provider]]  API keys - also tavily|exa|firecrawl
  kite web-keys [status|set|logout]  optional paid web tool keys
  kite providers                status, then pick to connect
  kite models [-p groq]         pick a model (--list to dump)
  kite config [--select-model] [--session-persistence full|redacted|disabled]
  kite privacy                  security policy summary

Project
  kite init [dir]               scaffold AGENTS.md (+ KITE.md); --chat for init skill
  kite context                  preview workspace discovery
  kite skills [--show name] [--add pkg|path]
  kite subagents [--show id] [--init id]   bundled + ~/.kite/subagents/
  kite commands | kite plugins
  kite memory [--remember text]
  kite gh issue view|list|create|comment [--repo o/r]   GitHub issues (GH_TOKEN works)
  kite gh pr view|list|create [--repo o/r]              GitHub PRs

Advanced
  kite runtime-config           merged agent TOML
  kite bench [--json] [--compare file]
  kite tasks init | kite tasks run <file> [--steps N] [--cost $] [--time S]
  kite apply | kite import | kite exec | kite audit | kite cloud | kite dashboard
  kite exec "task"              CI one-shot (headless, quiet, same flags as run)

REPL essentials (type /help in chat, /help all for everything)
  /build /plan                  apply edits (default) vs opt-in checklist-only
  /model [list|select|groq/id]  model picker (wheel / trackpad / ↑↓)
  /login /keys /select          credentials
  /checkpoint /handoff /compact session continuity
  /session list | /resume <id>  transcripts
  /status                       mode, model, cost, session persistence
  /privacy                      security policy; /privacy sessions …
  /stop /steer                  stop turn or redirect (session stays)
  /goal [text]            persistent objective; /goal pause|resume|clear
  /jobs /agents /kill [id|all]  crew board; /agents profiles|init|show
  /tools                        built-in agent tools (same glyphs as the transcript)

Flags on run: -p provider  -m model  --cwd PATH  --mode plan|build
  --approval auto|approve|supervised|yolo|trust|readonly  --headless  --no-stream
  --steps  --cost  --time  --role  --long  --attach PATH  -v  -q  --json  -o PATH
  --print (answer only)

Flags on chat (also interactive resume): -p  -m  --cwd  --mode  --approval
  --steps  --cost  --time  --role  --long  --attach PATH  --no-context  --no-compact
  --no-guardrails  -v

Persistent compaction: kite config --auto-compact true|false

""" + docs_help()
