"""Short CLI help — grouped quick reference for `kite help` and `--help` epilog."""

from __future__ import annotations

# Shown in `kite --help` / `kite help` (everything else: `kite help all`).
CLI_PRIMARY_COMMANDS: frozenset[str] = frozenset({
    "run",
    "resume",
    "setup",
    "sessions",
    "tasks",
    "help",
})

# Compatibility aliases — still work, hidden from default help.
CLI_HIDDEN_ALIASES: frozenset[str] = frozenset({"chat", "exec"})


def docs_help() -> str:
    from kite import __version__

    return (
        "docs\n"
        "  guide.md           visual walkthrough + example Q&A\n"
        "  kite_commands.md   CLI and slash map\n"
        "  CONTEXT.md         terms, including memory layers\n"
        "  architecture.md    layers and extension points\n"
        "  SECURITY.md        trust boundaries\n"
        f"  docs/RELEASE-{__version__}.md  current release notes\n"
    )


CLI_EPILOG = """commands:
  kite                 interactive session
  kite run             one-shot or headless task
  kite resume          continue work
  kite setup           onboarding
  kite sessions        history
  kite tasks           batches

run `kite help all` for the full map  ·  in REPL type /help all
"""


def cli_help_brief() -> str:
    return """Kite CLI

  kite                 interactive session
  kite run             one-shot or headless task
  kite resume          continue work
  kite setup           onboarding
  kite sessions        history
  kite tasks           batches

More: kite help all
REPL:  /help  ·  /help all
"""


def cli_help_text() -> str:
    return """Kite CLI - full reference

Session
  kite | kite chat              REPL (plan/build, /slash commands)
  kite run "task"               one-shot
  kite resume [id] [message]    continue session (omit id to pick)
  kite sessions                 pick a transcript to open / show / delete

Setup & model
  kite setup                    first-run wizard
  kite keys [--set [provider]]  API keys - also tavily|exa|firecrawl
  kite web-keys [status|set|logout]  optional paid web tool keys
  kite providers                status, then pick to connect
  kite models [-p groq]         pick a model (--list to dump)
  kite config [--select-model] [--session-persistence full|redacted|disabled]
  kite privacy                  security policy summary

Project
  kite context                  preview workspace discovery
  kite skills [--show name] [--add pkg|path]
  kite subagents [--show id] [--init id]   bundled + ~/.kite/subagents/
  kite commands | kite plugins
  kite memory [--remember text]

Advanced
  kite runtime-config           merged agent TOML
  kite bench [--json] [--compare file]
  kite tasks init | kite tasks run <file> [--steps N] [--cost $] [--time S]
  kite apply | kite import | kite exec | kite audit | kite cloud
  kite exec "task"          CI one-shot (headless, quiet, same flags as run)

REPL essentials (type /help in chat, /help all for everything)
  /plan /build                  checklist-only vs apply
  /model [list|select|groq/id]  model picker
  /login /keys /select          credentials
  /checkpoint /handoff /compact session continuity
  /session list | /resume <id>  transcripts
  /status                       mode, model, cost, session persistence
  /privacy                      security policy; /privacy sessions …
  /stop /steer                  stop turn or redirect (session stays)
  /goal [text]            persistent objective; /goal pause|resume|clear
  /jobs /agents /kill [id|all]  crew board; /agents profiles|init|show

Flags on run: -p provider  -m model  --cwd PATH  --mode plan|build
  --approval auto|approve|supervised|yolo|trust|readonly  --headless  --no-stream
  --steps  --cost  --time  --role  --long  --attach PATH  -v  -q  --json  -o PATH

Flags on chat (also interactive resume): -p  -m  --cwd  --mode  --approval
  --steps  --cost  --time  --role  --long  --attach PATH  --no-context  --no-compact
  --no-guardrails  -v

Persistent compaction: kite config --auto-compact true|false

""" + docs_help()
