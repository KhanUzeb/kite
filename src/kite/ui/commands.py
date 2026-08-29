"""Slash commands — control-plane, never mixed into the task conversation."""

from __future__ import annotations

from dataclasses import dataclass

HELP = """\
/plan              switch to plan mode (read-only, produce a checklist)
/build             switch to build mode (apply edits, gated bash)
/model [id]        show or set provider/model
/undo              revert the last kite task commit
/clear             start a fresh session
/compact           compact context now
/cost              session tokens and USD
/status            mode, model, cost, session id
/session           show current session id
/init              write KITE.md project memory
/expand            expand last collapsed tool output
/trace             show last error traceback
/approve auto|approve|readonly
/skills [name]     list skills, or show one
/skill name [args] run a skill as this turn
/commands          list markdown slash commands
/commands new name write .kite/commands/name.md
/plugins           list plugins
/plugins init name scaffold .kite/plugins/name
/memory            show durable notes
/remember [user|project] text
/forget id|text    drop matching notes
/home              show ~/.kite paths
/help              this list
/quit              exit
"""

CONTROL_COMMANDS = frozenset(
    {
        "plan",
        "build",
        "model",
        "undo",
        "clear",
        "compact",
        "cost",
        "init",
        "expand",
        "trace",
        "approve",
        "help",
        "quit",
        "mode",
        "skills",
        "skill",
        "commands",
        "plugins",
        "memory",
        "remember",
        "forget",
        "status",
        "session",
        "new",
        "home",
    }
)


@dataclass(frozen=True)
class SlashResult:
    kind: str  # handled | unknown | not_slash | quit | prompt
    command: str = ""
    arg: str = ""
    message: str = ""
    prompt: str = ""
    source: str = ""


def parse_slash(raw: str) -> SlashResult:
    text = raw.strip()
    if not text.startswith("/"):
        return SlashResult("not_slash")
    if text.startswith("//"):
        # escaped natural-language that happens to start with /
        return SlashResult("not_slash")
    body = text[1:]
    cmd, _, rest = body.partition(" ")
    cmd = cmd.lower().strip()
    arg = rest.strip()
    aliases = {
        "q": "quit",
        "exit": "quit",
        "p": "plan",
        "b": "build",
        "h": "help",
        "mem": "memory",
        "cmd": "commands",
        "cmds": "commands",
    }
    cmd = aliases.get(cmd, cmd)
    if cmd in CONTROL_COMMANDS:
        return SlashResult("handled", command=cmd, arg=arg)
    return SlashResult("unknown", command=cmd, arg=arg, message=f"unknown command /{cmd}  — /help")
