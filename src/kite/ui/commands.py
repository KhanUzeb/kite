"""Slash commands — control-plane, never mixed into the task conversation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinCommand:
    name: str
    description: str
    hint: str = ""
    group: str = "session"
    aliases: tuple[str, ...] = ()


BUILTINS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("plan", "Read-only mode — produce a checklist", aliases=("p",), group="session"),
    BuiltinCommand("build", "Apply edits, gated bash", aliases=("b",), group="session"),
    BuiltinCommand("approve", "Autonomy for this session", hint="auto|approve|readonly", group="session"),
    BuiltinCommand("undo", "Revert the last kite: git checkpoint", group="session"),
    BuiltinCommand("clear", "Fresh chat session (memory stays)", aliases=("new",), group="session"),
    BuiltinCommand("compact", "Summarize older turns now (OpenRouter free)", group="session"),
    BuiltinCommand("expand", "Show full tool output next turn", group="session"),
    BuiltinCommand("cost", "Session tokens and USD", group="session"),
    BuiltinCommand("status", "Mode, model, effort, session id", group="session"),
    BuiltinCommand("session", "Show, list, open, or delete transcripts", hint="[list|show|open|delete]", aliases=("sessions",), group="session"),
    BuiltinCommand("resume", "Continue a saved session", hint="id", group="session"),
    BuiltinCommand("init", "Write KITE.md project memory", group="session"),
    BuiltinCommand("trace", "Last error traceback", group="session"),
    BuiltinCommand("home", "Show ~/.kite paths", group="session"),
    BuiltinCommand("help", "This map", aliases=("h",), group="session"),
    BuiltinCommand("quit", "Leave the REPL", aliases=("q", "exit"), group="session"),
    BuiltinCommand("model", "Show or set provider/model", hint="provider/id", group="model"),
    BuiltinCommand("models", "List live models for the current provider", group="model"),
    BuiltinCommand("provider", "Show or set provider", hint="name", group="model"),
    BuiltinCommand("thinking", "Extended thinking (if this model supports it)", group="model"),
    BuiltinCommand("fast", "Low effort / low latency (if supported)", group="model"),
    BuiltinCommand("reasoning", "auto | off | fast | thinking", hint="auto|off|fast|thinking", aliases=("effort",), group="model"),
    BuiltinCommand("memory", "Semantic markdown + episodic sqlite", hint="semantic|episodic", aliases=("mem",), group="memory"),
    BuiltinCommand("semantic", "Show markdown semantic memory", group="memory"),
    BuiltinCommand("episodic", "Show sqlite episode log", group="memory"),
    BuiltinCommand("remember", "Append a semantic note", hint="[user|project] text", group="memory"),
    BuiltinCommand("forget", "Drop matching notes or episodes", hint="id|substring", group="memory"),
    BuiltinCommand("skills", "List skills, or show one", hint="name", group="extensions"),
    BuiltinCommand("skill", "Run a skill as this turn", hint="name [args]", group="extensions"),
    BuiltinCommand("commands", "List markdown slash prompts", hint="new name", aliases=("cmd", "cmds"), group="extensions"),
    BuiltinCommand("plugins", "List plugins, or scaffold one", hint="init name", aliases=("plugin",), group="extensions"),
    BuiltinCommand("attach", "Attach a file or image to the next turn", hint="path", group="attach"),
    BuiltinCommand("clip", "Attach the clipboard (text or image)", aliases=("clipboard", "paste"), group="attach"),
    BuiltinCommand("detach", "Drop a pending attachment", hint="name|all", group="attach"),
    BuiltinCommand("attachments", "List files queued for the next turn", group="attach"),
)

CONTROL_COMMANDS = frozenset(b.name for b in BUILTINS)

ALIASES: dict[str, str] = {}
for _b in BUILTINS:
    for _a in _b.aliases:
        ALIASES[_a] = _b.name

ARG_CHOICES: dict[str, list[tuple[str, str]]] = {
    "approve": [
        ("auto", "run tools without asking"),
        ("approve", "ask before mutating"),
        ("readonly", "block writes and bash"),
    ],
    "reasoning": [
        ("auto", "provider default"),
        ("off", "disable extended thinking"),
        ("fast", "low effort / low latency"),
        ("thinking", "extended thinking"),
    ],
    "effort": [
        ("auto", "provider default"),
        ("off", "disable extended thinking"),
        ("fast", "low effort / low latency"),
        ("thinking", "extended thinking"),
    ],
    "mode": [
        ("plan", "read-only checklist"),
        ("build", "apply edits"),
    ],
}

HELP = "\n".join(
    f"/{b.name:<16} {b.hint + '  ' if b.hint else ''}{b.description}".rstrip()
    for b in BUILTINS
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
    cmd = ALIASES.get(cmd, cmd)
    if cmd in CONTROL_COMMANDS:
        return SlashResult("handled", command=cmd, arg=arg)
    return SlashResult("unknown", command=cmd, arg=arg, message=f"unknown command /{cmd}  — type / for the list")
