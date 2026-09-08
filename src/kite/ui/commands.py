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
    BuiltinCommand("plan", "Read-only — explore, checklist, then stop", aliases=("p",), group="session"),
    BuiltinCommand("build", "Apply edits from the checklist", aliases=("b",), group="session"),
    BuiltinCommand("approve", "Autonomy: yolo|auto|supervised", hint="[yolo|auto|supervised]", group="session"),
    BuiltinCommand("restricted", "Path sandbox — off by default (host mode)", hint="[on|off]", aliases=("sandbox",), group="session"),
    BuiltinCommand("undo", "Revert the last kite: git checkpoint", group="session"),
    BuiltinCommand("clear", "Fresh chat session (memory stays)", aliases=("new",), group="session"),
    BuiltinCommand("compact", "Summarize older turns now (OpenRouter free)", group="session"),
    BuiltinCommand("checkpoint", "Save/list/restore transcript snapshot", hint="save|list|restore|show", group="session"),
    BuiltinCommand("handoff", "Export context for another agent", hint="[dir]", group="session"),
    BuiltinCommand("expand", "Toggle expanded tool output", group="session"),
    BuiltinCommand("live", "Stream bash output in real time while tools run", group="session"),
    BuiltinCommand("expand-thinking", "Show or hide model thinking trace (expanded by default)", hint="collapse", group="session"),
    BuiltinCommand("collapse", "Collapse tool output (default)", group="session"),
    BuiltinCommand("status", "Mode, model, effort, cost, session id, privacy", group="session"),
    BuiltinCommand(
        "privacy",
        "Session persistence and security policy",
        hint="[sessions full|redacted|disabled]",
        group="session",
    ),
    BuiltinCommand("stop", "Stop the current turn — session stays open", group="session"),
    BuiltinCommand("steer", "Stop and inject a correction as the next turn", hint="text", group="session"),
    BuiltinCommand("tasks", "Show the running turn and queued follow-ups", group="session"),
    BuiltinCommand("jobs", "List background bash jobs and live subagents", group="session"),
    BuiltinCommand("kill", "Kill a background job or subagent", hint="[id|all]", group="session"),
    BuiltinCommand("session", "Show, list, open, or delete transcripts", hint="[list|show|open|delete]", aliases=("sessions",), group="session"),
    BuiltinCommand("resume", "Continue a saved session", hint="[id]", group="session"),
    BuiltinCommand("init", "Write KITE.md project memory", group="session"),
    BuiltinCommand("trace", "Last error traceback", group="session"),
    BuiltinCommand("home", "Show ~/.kite paths", group="session"),
    BuiltinCommand("help", "This map", aliases=("h",), group="session"),
    BuiltinCommand("quit", "Leave the REPL", aliases=("q", "exit"), group="session"),
    BuiltinCommand("theme", "Color palette", hint="auto|kite|dark|light|dim|mono|monochrome|catppuccin|ember|forest|hues", group="session"),
    BuiltinCommand("font", "Glyphs for this terminal", hint="unicode|ascii", group="session"),
    BuiltinCommand("setup", "First-run wizard (BYOK key or BYOS OAuth + model)", group="model"),
    BuiltinCommand(
        "login",
        "Link provider (opens browser for BYOS) then pick a model",
        hint="provider",
        aliases=("signin",),
        group="model",
    ),
    BuiltinCommand(
        "logout",
        "Unlink provider — remove API key or OAuth session",
        hint="provider",
        aliases=("signout",),
        group="model",
    ),
    BuiltinCommand("keys", "Show BYOK keys and BYOS OAuth link status", group="model"),
    BuiltinCommand("model", "Show, set, list, or pick model", hint="list|select|provider/id", group="model"),
    BuiltinCommand("models", "Pick a live model and save it to config", hint="[provider|refresh]", group="model"),
    BuiltinCommand("select", "Interactive model picker (saved to ~/.kite/config.toml)", hint="[provider]", group="model"),
    BuiltinCommand("provider", "Show or pick provider, then a model", hint="[name]", group="model"),
    BuiltinCommand("refresh", "Re-fetch live models from the API, then pick", hint="[provider]", group="model"),
    BuiltinCommand("reasoning", "auto | off | fast | thinking", hint="auto|off|fast|thinking", aliases=("effort",), group="model"),
    BuiltinCommand("memory", "Semantic MEMORY.md + episodic log", hint="semantic|episodic", aliases=("mem",), group="memory"),
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

# Legacy shortcuts — still parsed; listed under “legacy aliases” in /help.
LEGACY_ALIASES: dict[str, str] = {
    "cost": "status",
    "thinking": "reasoning",
    "fast": "reasoning",
    "semantic": "memory",
    "episodic": "memory",
}

LEGACY_HELP: dict[str, str] = {
    "cost": "→ /status (includes cost)",
    "thinking": "→ /reasoning thinking",
    "fast": "→ /reasoning fast",
    "semantic": "→ /memory semantic",
    "episodic": "→ /memory episodic",
}

ARG_CHOICES: dict[str, list[tuple[str, str]]] = {
    "approve": [
        ("yolo", "skip in-workspace prompts; high-risk still asks"),
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
        ("refresh", "re-fetch models from API"),
    ],
    "models": [
        ("refresh", "re-fetch models from API, then pick"),
    ],
    "mode": [
        ("plan", "explore + checklist, no edits"),
        ("build", "apply checklist / edits"),
    ],
    "theme": [
        ("auto", "follow the terminal"),
        ("kite", "bright cyan on dark"),
        ("dark", "near-black UI, bright cyan accents"),
        ("light", "blue brand on light terminals"),
        ("dim", "low-contrast"),
        ("mono", "no color, bold errors only"),
        ("monochrome", "grayscale with subtle contrast"),
        ("catppuccin", "pastel mocha — lavender brand, pink accent"),
        ("ember", "warm charcoal — amber brand, ember glow"),
        ("forest", "deep green — moss brand, leaf accent"),
        ("hues", "vivid accents — purple brand, rainbow tools"),
    ],
    "font": [
        ("unicode", "+ ! > * — plain symbols (default)"),
        ("ascii", "+ ! > — strict 7-bit ASCII"),
    ],
    "kill": [
        ("all", "kill every background job and live subagent"),
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
    "privacy": [
        ("sessions", "show or pick session persistence mode"),
        ("sessions redacted", "sanitize secrets before session write (default)"),
        ("sessions full", "persist raw session JSONL (opt-in)"),
        ("sessions disabled", "no session file writes"),
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
