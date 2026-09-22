"""Slash commands — control-plane, never mixed into the task conversation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kite.ui.theme import FONT_HELP, THEME_HELP

Visibility = Literal["primary", "advanced"]


@dataclass(frozen=True)
class BuiltinCommand:
    name: str
    description: str
    hint: str = ""
    group: str = "session"
    aliases: tuple[str, ...] = ()
    visibility: Visibility = "advanced"


PRIMARY_SLASH_COMMANDS: frozenset[str] = frozenset({
    "build",
    "plan",
    "new",
    "usage",
    "status",
    "model",
    "session",
    "memory",
    "agents",
    "attach",
    "skills",
    "theme",
    "help",
    "quit",
})


BUILTINS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand(
        "build",
        "Apply edits (default) — continues any plan checklist",
        hint="[text]",
        aliases=("b",),
        group="session",
        visibility="primary",
    ),
    BuiltinCommand(
        "plan",
        "Opt-in read-only explore + checklist — /build to apply",
        hint="[text]",
        aliases=("p",),
        group="session",
        visibility="primary",
    ),
    BuiltinCommand("approve", "Autonomy: yolo|auto|supervised", hint="[yolo|auto|supervised]", group="session"),
    BuiltinCommand(
        "trust",
        "Trust this project — skip nested-agent approval; load .kite/plugins freely",
        hint="[on|off|status]",
        group="session",
    ),
    BuiltinCommand("reload", "Reload skills, slash commands, and subagent profiles", group="session"),
    BuiltinCommand("hotkeys", "Keyboard shortcuts (Pi /hotkeys)", group="session", aliases=("keys-help",)),
    BuiltinCommand("restricted", "Path sandbox — off by default (host mode)", hint="[on|off]", aliases=("sandbox",), group="session"),
    BuiltinCommand("undo", "Revert the last kite: git checkpoint", group="session"),
    BuiltinCommand("clear", "Fresh chat session (memory stays)", group="session"),
    BuiltinCommand(
        "new",
        "Start a new session — clears history, keeps provider/model",
        group="session",
        visibility="primary",
    ),
    BuiltinCommand("compact", "Summarize older turns now (OpenRouter free)", group="session"),
    BuiltinCommand("checkpoint", "Save/list/restore transcript snapshot", hint="save|list|restore|show", group="session"),
    BuiltinCommand("handoff", "Export context for another agent", hint="[dir]", group="session"),
    BuiltinCommand("expand", "Toggle expanded tool output", group="session"),
    BuiltinCommand(
        "live",
        "Stream output live — /live (bash) or /live agents (subagent crew)",
        hint="[agents]",
        group="session",
    ),
    BuiltinCommand("expand-thinking", "Show or hide model thinking trace (expanded by default)", hint="collapse", group="session"),
    BuiltinCommand("collapse", "Collapse tool output (default)", group="session"),
    BuiltinCommand(
        "status",
        "Mode, model, cost, shortcuts, paths, privacy",
        group="session",
        visibility="primary",
    ),
    BuiltinCommand(
        "usage",
        "Token, cache, cost, context, and provider limits",
        hint="[session|provider|all]",
        group="session",
        visibility="primary",
    ),
    BuiltinCommand(
        "privacy",
        "Session persistence and security policy",
        hint="[sessions full|redacted|disabled]",
        group="session",
    ),
    BuiltinCommand("stop", "Stop the current turn — session stays open", group="session"),
    BuiltinCommand("steer", "Inject a correction into the running turn (queues when idle)", hint="text", group="session"),
    BuiltinCommand("tasks", "Show the running turn and queued follow-ups", group="session"),
    BuiltinCommand(
        "goal",
        "Persistent long-horizon objective (survives provider errors)",
        hint="[text]|pause|resume|clear|edit",
        group="session",
    ),
    BuiltinCommand("jobs", "List background bash jobs and live subagents", group="session"),
    BuiltinCommand(
        "agents",
        "Crew, jobs, tasks, kill, personas",
        hint="profiles|show <id>|init <id>|reload",
        group="session",
        visibility="primary",
    ),
    BuiltinCommand("kill", "Kill a background job or subagent", hint="[id|all]", group="session"),
    BuiltinCommand(
        "session",
        "Resume, clear, compact, checkpoint, handoff, privacy",
        hint="[list|show|open|delete]",
        aliases=("sessions",),
        group="session",
        visibility="primary",
    ),
    BuiltinCommand("resume", "Continue a saved session", hint="[id]", group="session"),
    BuiltinCommand("init", "Scaffold AGENTS.md (+ KITE.md); /init --force to overwrite", group="session"),
    BuiltinCommand("context", "Preview discovered project context for this workspace", group="session"),
    BuiltinCommand("trace", "Last error traceback", group="session"),
    BuiltinCommand("home", "Show ~/.kite paths", group="session"),
    BuiltinCommand(
        "help",
        "Essential commands; /help all for the full map",
        aliases=("h",),
        group="session",
        visibility="primary",
    ),
    BuiltinCommand(
        "quit",
        "Leave the REPL",
        aliases=("q", "exit"),
        group="session",
        visibility="primary",
    ),
    BuiltinCommand(
        "theme",
        "Color palette",
        hint="auto|kite|dark|light|dim|mono|monochrome|catppuccin|ember|forest|hues|transparent",
        group="session",
        visibility="primary",
    ),
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
    BuiltinCommand(
        "model",
        "Provider, login, keys, model pick, reasoning",
        hint="list|select|provider/id",
        group="model",
        visibility="primary",
    ),
    BuiltinCommand("models", "Pick a live model and save it to config", hint="[provider|refresh]", group="model"),
    BuiltinCommand("select", "Interactive model picker (saved to ~/.kite/config.toml)", hint="[provider]", group="model"),
    BuiltinCommand("provider", "Show or pick provider, then a model", hint="[name]", group="model"),
    BuiltinCommand("refresh", "Re-fetch live models from the API, then pick", hint="[provider]", group="model"),
    BuiltinCommand(
        "thinking",
        "off | minimal | low | medium | high — empty cycles (Pi-style)",
        hint="off|minimal|low|medium|high",
        group="model",
        visibility="primary",
    ),
    BuiltinCommand(
        "reasoning",
        "Legacy effort modes — prefer /thinking",
        hint="auto|off|fast|thinking",
        aliases=("effort",),
        group="model",
    ),
    BuiltinCommand(
        "memory",
        "User, profile, working style, remember, forget",
        hint="semantic|episodic",
        aliases=("mem",),
        group="memory",
        visibility="primary",
    ),
    BuiltinCommand("user", "Global identity (~/.kite/memory/USER.md)", hint="[add text]", group="memory"),
    BuiltinCommand(
        "profile",
        "Global stack/goals (~/.kite/memory/PROFILE.md) — not subagent personas",
        hint="[add text]",
        group="memory",
    ),
    BuiltinCommand("working", "Fluid working rhythm (~/.kite/memory/WORKING.md)", hint="[add text]", group="memory"),
    BuiltinCommand("remember", "Append a semantic note", hint="[user|project] text", group="memory"),
    BuiltinCommand("forget", "Drop matching notes or episodes", hint="id|substring", group="memory"),
    BuiltinCommand(
        "skills",
        "List, show, or install a skill",
        hint="[add pkg]|name",
        group="extensions",
        visibility="primary",
    ),
    BuiltinCommand("skill", "Run a skill as this turn", hint="name [args]", group="extensions"),
    BuiltinCommand(
        "tools",
        "Built-in agent tools with the same glyphs as the transcript",
        aliases=("tool",),
        group="extensions",
    ),
    BuiltinCommand("commands", "List markdown slash prompts", hint="new name", aliases=("cmd", "cmds"), group="extensions"),
    BuiltinCommand("plugins", "List plugins, or scaffold one", hint="init name", aliases=("plugin",), group="extensions"),
    BuiltinCommand(
        "attach",
        "Files, clipboard, list, detach",
        hint="path",
        group="attach",
        visibility="primary",
    ),
    BuiltinCommand("clip", "Attach the clipboard (text or image)", aliases=("clipboard", "paste"), group="attach"),
    BuiltinCommand("detach", "Drop a pending attachment", hint="name|all", group="attach"),
    BuiltinCommand("attachments", "List files queued for the next turn", group="attach"),
)

CONTROL_COMMANDS = frozenset(b.name for b in BUILTINS)

ALIASES: dict[str, str] = {}
for _b in BUILTINS:
    for _a in _b.aliases:
        ALIASES[_a] = _b.name


def resolve_slash_name(name: str) -> str:
    key = (name or "").strip().lower()
    return ALIASES.get(key, key)


def is_primary_slash(name: str) -> bool:
    return resolve_slash_name(name) in PRIMARY_SLASH_COMMANDS


def primary_builtins() -> tuple[BuiltinCommand, ...]:
    return tuple(b for b in BUILTINS if b.visibility == "primary")


# Legacy shortcuts — still parsed; listed under “legacy aliases” in /help.
LEGACY_ALIASES: dict[str, str] = {
    "cost": "status",
    "fast": "thinking",
    "semantic": "memory",
    "episodic": "memory",
}

LEGACY_HELP: dict[str, str] = {
    "cost": "→ /status (includes cost)",
    "fast": "→ /thinking low",
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
    "thinking": [
        ("off", "disable extended thinking"),
        ("minimal", "least thinking / lowest latency"),
        ("low", "low effort / low latency"),
        ("medium", "balanced"),
        ("high", "extended thinking"),
        ("xhigh", "max thinking (when supported)"),
        ("max", "max thinking (when supported)"),
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
        ("build", "apply edits (default)"),
        ("plan", "opt-in: explore + checklist, no edits"),
    ],
    "theme": [(name, THEME_HELP[name]) for name in THEME_HELP],
    "font": [(name, FONT_HELP[name]) for name in FONT_HELP],
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
    "agents": [
        ("profiles", "list bundled + custom subagent personas"),
        ("show", "print one persona by id"),
        ("init", "scaffold ~/.kite/subagents/<id>.md"),
        ("reload", "reload profiles from disk"),
    ],
    "usage": [
        ("session", "current session totals"),
        ("provider", "provider-reported limits and reset times"),
        ("all", "local totals plus provider information"),
        ("show", "same as session (default report)"),
    ],
    "goal": [
        ("pause", "suspend goal auto-continue"),
        ("resume", "reactivate goal"),
        ("clear", "remove goal"),
        ("edit", "revise objective text"),
    ],
}

ARG_CHOICES["effort"] = ARG_CHOICES["reasoning"]
ARG_CHOICES["fast"] = ARG_CHOICES["thinking"]
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
