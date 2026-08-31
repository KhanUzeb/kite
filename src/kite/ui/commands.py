"""Slash commands — control-plane, never mixed into the task conversation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinCommand:
    name: str
    description: str
    hint: str = ""
    group: str = "chat"
    aliases: tuple[str, ...] = ()


# Shown in /help — legacy names (provider, models, select, cost, thinking, …) still work in repl.py
BUILTINS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand("plan", "Read-only checklist mode", aliases=("p",), group="chat"),
    BuiltinCommand("build", "Apply edits (gated bash)", aliases=("b",), group="chat"),
    BuiltinCommand("approve", "Session autonomy", hint="auto|approve|readonly", group="chat"),
    BuiltinCommand("undo", "Revert last kite: git checkpoint", group="chat"),
    BuiltinCommand("clear", "Fresh chat (memory stays)", aliases=("new",), group="chat"),
    BuiltinCommand("compact", "Summarize older turns now", group="chat"),
    BuiltinCommand("checkpoint", "Save/list/restore transcript", hint="save|list|restore|show", group="chat"),
    BuiltinCommand("handoff", "Export context for another agent", hint="[dir]", group="chat"),
    BuiltinCommand("expand", "Toggle tool output detail", group="chat"),
    BuiltinCommand("status", "Mode, model, cost, session id", group="chat"),
    BuiltinCommand("session", "List, show, open, delete transcripts", hint="list|show|open|delete", aliases=("sessions",), group="chat"),
    BuiltinCommand("resume", "Continue a saved session", hint="id", group="chat"),
    BuiltinCommand("init", "Write KITE.md if missing", group="chat"),
    BuiltinCommand("trace", "Last error traceback", group="chat"),
    BuiltinCommand("theme", "Color palette", hint="auto|kite|dark|light|dim|mono", group="chat"),
    BuiltinCommand("font", "Terminal glyphs", hint="unicode|ascii", group="chat"),
    BuiltinCommand("home", "Show ~/.kite paths", group="chat"),
    BuiltinCommand("help", "Command map", aliases=("h",), group="chat"),
    BuiltinCommand("quit", "Leave REPL", aliases=("q", "exit"), group="chat"),
    BuiltinCommand("model", "Show, set, list, or pick model", hint="list|select|provider/id", group="model"),
    BuiltinCommand("login", "Save API key (hidden)", hint="provider", aliases=("signin",), group="model"),
    BuiltinCommand("logout", "Remove API key", hint="provider", aliases=("signout",), group="model"),
    BuiltinCommand("keys", "Which provider keys are set", group="model"),
    BuiltinCommand("setup", "First-run wizard (key + model)", group="model"),
    BuiltinCommand("reasoning", "Effort: auto|off|fast|thinking", hint="level", aliases=("effort",), group="model"),
    BuiltinCommand("memory", "Notes: semantic + episodic", hint="semantic|episodic", aliases=("mem",), group="memory"),
    BuiltinCommand("remember", "Append a note", hint="[user|project] text", group="memory"),
    BuiltinCommand("forget", "Drop matching notes", hint="id|substring", group="memory"),
    BuiltinCommand("skills", "List, show, or install skills", hint="add pkg|name", group="extensions"),
    BuiltinCommand("commands", "Markdown slash prompts", hint="new name", aliases=("cmd", "cmds"), group="extensions"),
    BuiltinCommand("plugins", "List or scaffold plugins", hint="init name", aliases=("plugin",), group="extensions"),
    BuiltinCommand("attach", "File/image for next turn", hint="path", group="attach"),
    BuiltinCommand("clip", "Clipboard for next turn", aliases=("clipboard", "paste"), group="attach"),
    BuiltinCommand("detach", "Drop attachment", hint="name|all", group="attach"),
    BuiltinCommand("attachments", "Queued attachments", group="attach"),
)

CONTROL_COMMANDS = frozenset(b.name for b in BUILTINS)

ALIASES: dict[str, str] = {}
for _b in BUILTINS:
    for _a in _b.aliases:
        ALIASES[_a] = _b.name

# Legacy shortcuts — hidden from /help but still parsed
LEGACY_ALIASES: dict[str, str] = {
    "provider": "model",
    "models": "model",
    "select": "model",
    "cost": "status",
    "collapse": "expand",
    "thinking": "reasoning",
    "fast": "reasoning",
    "semantic": "memory",
    "episodic": "memory",
    "skill": "skills",
}

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
    "model": [
        ("list", "live models for provider"),
        ("select", "interactive picker"),
    ],
    "mode": [
        ("plan", "read-only checklist"),
        ("build", "apply edits"),
    ],
    "theme": [
        ("auto", "follow the terminal"),
        ("kite", "cyan brand on dark"),
        ("dark", "cyan brand, dark composer"),
        ("light", "blue brand on light terminals"),
        ("dim", "low-contrast"),
        ("mono", "no color, bold errors only"),
    ],
    "font": [
        ("unicode", "✓ ⚠ › — default"),
        ("ascii", "+ ! > — plain ASCII"),
    ],
    "checkpoint": [
        ("save", "snapshot current transcript"),
        ("list", "list checkpoints for this session"),
        ("restore", "restore transcript from checkpoint id"),
        ("show", "preview checkpoint summary"),
    ],
    "memory": [
        ("semantic", "markdown notes"),
        ("episodic", "sqlite episode log"),
    ],
}

ARG_CHOICES["effort"] = ARG_CHOICES["reasoning"]


@dataclass(frozen=True)
class SlashResult:
    kind: str  # handled | unknown | not_slash | quit | prompt
    command: str = ""
    arg: str = ""
    message: str = ""
    prompt: str = ""
    source: str = ""
    legacy: str = ""  # original cmd before legacy alias rewrite


def parse_slash(raw: str) -> SlashResult:
    text = raw.strip()
    if not text.startswith("/"):
        return SlashResult("not_slash")
    if text.startswith("//"):
        return SlashResult("not_slash")
    body = text[1:]
    cmd, _, rest = body.partition(" ")
    original = cmd.lower().strip()
    arg = rest.strip()
    cmd = ALIASES.get(original, original)
    legacy = ""
    if original in LEGACY_ALIASES:
        legacy = original
        mapped = LEGACY_ALIASES[original]
        if mapped == cmd:
            pass
        else:
            cmd = mapped
    if cmd in CONTROL_COMMANDS or legacy:
        return SlashResult("handled", command=cmd, arg=arg, legacy=legacy)
    return SlashResult("unknown", command=cmd, arg=arg, message=f"unknown command /{original}  — type /help")
