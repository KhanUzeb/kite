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
    BuiltinCommand("approve", "Autonomy: yolo|auto|supervised", hint="yolo|auto|supervised|trust|readonly", group="session"),
    BuiltinCommand("restricted", "Path sandbox — off by default (host mode)", hint="on|off", aliases=("sandbox",), group="session"),
    BuiltinCommand("undo", "Revert the last kite: git checkpoint", group="session"),
    BuiltinCommand("clear", "Fresh chat session (memory stays)", aliases=("new",), group="session"),
    BuiltinCommand("compact", "Summarize older turns now (OpenRouter free)", group="session"),
    BuiltinCommand("checkpoint", "Save/list/restore transcript snapshot", hint="save|list|restore|show", group="session"),
    BuiltinCommand("handoff", "Export context for another agent", hint="[dir]", group="session"),
    BuiltinCommand("expand", "Toggle expanded tool output", group="session"),
    BuiltinCommand("collapse", "Collapse tool output (default)", group="session"),
    BuiltinCommand("cost", "Session tokens and USD", group="session"),
    BuiltinCommand("status", "Mode, model, effort, session id", group="session"),
    BuiltinCommand("session", "Show, list, open, or delete transcripts", hint="[list|show|open|delete]", aliases=("sessions",), group="session"),
    BuiltinCommand("resume", "Continue a saved session", hint="id", group="session"),
    BuiltinCommand("init", "Write KITE.md project memory", group="session"),
    BuiltinCommand("trace", "Last error traceback", group="session"),
    BuiltinCommand("home", "Show ~/.kite paths", group="session"),
    BuiltinCommand("help", "This map", aliases=("h",), group="session"),
    BuiltinCommand("quit", "Leave the REPL", aliases=("q", "exit"), group="session"),
    BuiltinCommand("theme", "Color palette", hint="auto|kite|dark|light|dim|mono", group="session"),
    BuiltinCommand("font", "Glyphs for this terminal", hint="unicode|ascii", group="session"),
    BuiltinCommand("setup", "First-run wizard (API key + model)", group="model"),
    BuiltinCommand("login", "Save provider API key to ~/.kite/.env (hidden input)", hint="provider", aliases=("signin",), group="model"),
    BuiltinCommand("logout", "Remove provider API key from ~/.kite/.env", hint="provider", aliases=("signout",), group="model"),
    BuiltinCommand("keys", "Show which provider API keys are set", group="model"),
    BuiltinCommand("model", "Show, set, list, or pick model", hint="list|select|provider/id", group="model"),
    BuiltinCommand("models", "List live models for the current provider", group="model"),
    BuiltinCommand("select", "Interactive model picker (saved to ~/.kite/config.toml)", hint="[provider]", group="model"),
    BuiltinCommand("provider", "Show or set provider", hint="name", group="model"),
    BuiltinCommand("thinking", "Thinking level (only if this API has thinking and fast)", hint="level", group="model"),
    BuiltinCommand("fast", "Fast level (only if this API has thinking and fast)", hint="level", group="model"),
    BuiltinCommand("reasoning", "auto | off | fast | thinking", hint="auto|off|fast|thinking", aliases=("effort",), group="model"),
    BuiltinCommand("memory", "Semantic markdown + episodic sqlite", hint="semantic|episodic", aliases=("mem",), group="memory"),
    BuiltinCommand("semantic", "Show markdown semantic memory", group="memory"),
    BuiltinCommand("episodic", "Show sqlite episode log", group="memory"),
    BuiltinCommand("remember", "Append a semantic note", hint="[user|project] text", group="memory"),
    BuiltinCommand("forget", "Drop matching notes or episodes", hint="id|substring", group="memory"),
    BuiltinCommand("skills", "List, show, or install a skill", hint="[add pkg]|name", group="extensions"),
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

# Legacy shortcuts — still parsed; also listed in /help when not duplicated above.
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
        ("yolo", "no prompts — everything allowed"),
        ("auto", "auto in workspace; ask outside project"),
        ("supervised", "reads free; write/bash need approval"),
        ("approve", "alias for supervised"),
        ("trust", "auto writes; safe bash in workspace"),
        ("readonly", "block mutations"),
    ],
    "restricted": [
        ("on", "clamp paths to session cwd"),
        ("off", "host mode (default)"),
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
ARG_CHOICES["sandbox"] = ARG_CHOICES["restricted"]


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
        if mapped != cmd:
            cmd = mapped
    if cmd in CONTROL_COMMANDS or legacy:
        return SlashResult("handled", command=cmd, arg=arg, legacy=legacy)
    return SlashResult("unknown", command=cmd, arg=arg, message=f"unknown command /{original}  — type /help")
