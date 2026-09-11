"""Tool contracts and effect derivation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["ok", "error", "denied", "cancelled"]

SideEffect = Literal[
    "workspace_read",
    "workspace_write",
    "destructive",
    "network",
    "durable_memory",
    "package_or_skill_install",
    "nested_agent",
    "long_running",
    # Legacy aliases — prefer canonical names above
    "read",
    "external_write",
    "sensitive_read",
    "process_control",
    "cost_bearing",
]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    source: str = "model"


@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool: str
    normalized_arguments: dict[str, Any]
    canonical_targets: tuple[str, ...]
    side_effects: tuple[SideEffect, ...]
    workspace: str
    command_digest: str = ""
    content_digest: str = ""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    mandatory: bool = False
    policy_version: str = "0.9.0"
    scope: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    status: ToolStatus
    ok: bool
    output: str = ""
    error: str = ""
    changed_paths: tuple[str, ...] = ()
    duration: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Static scheduling hints — PolicyEngine.authorize remains authoritative.
TOOL_SIDE_EFFECTS: dict[str, tuple[SideEffect, ...]] = {
    "read": ("workspace_read",),
    "grep": ("workspace_read",),
    "glob": ("workspace_read",),
    "ls": ("workspace_read",),
    "write": ("workspace_write",),
    "edit": ("workspace_write",),
    "apply_patch": ("workspace_write",),
    "bash": ("long_running", "workspace_write"),
    "web_search": ("network", "workspace_read"),
    "web_fetch": ("network", "workspace_read"),
    "task": ("nested_agent", "long_running"),
    "subagent": ("nested_agent", "long_running"),
    "memory": ("workspace_read",),
    "skill": ("workspace_read",),
    "memory_write": ("durable_memory",),
}


def side_effects_for(tool_name: str) -> tuple[SideEffect, ...]:
    """Default effects by tool name — use derive_effects(call) for authorization."""
    return TOOL_SIDE_EFFECTS.get(tool_name, ("workspace_read", "workspace_write"))



_LEGACY_EFFECT_MAP: dict[str, SideEffect] = {
    "read": "workspace_read",
    "process_control": "long_running",
    "cost_bearing": "network",
    "external_write": "destructive",
    "sensitive_read": "durable_memory",
}

_DESTRUCTIVE_BASH = re.compile(
    r"(?i)\b("
    r"rm\b|rmdir\b|del\b|remove-item\b|erase\b"
    r"|git\s+(reset|rebase|clean|push|commit)"
    r"|chmod\b|chown\b|takeown\b"
    r")\b"
)
_NETWORK_BASH = re.compile(
    r"(?i)\b(curl\b|wget\b|invoke-webrequest\b|iwr\b|ssh\b|scp\b|nc\b)\b"
)
_PACKAGE_INSTALL = re.compile(
    r"(?i)\b(pip3?|npm|yarn|pnpm|cargo|apt|apt-get|brew|dnf|yum)\s+"
    r"(install|uninstall|ci|add|remove)\b"
)
_GIT_NETWORK = re.compile(r"(?i)\bgit\s+(clone|pull|push)\b")
_CLOUD_CLI = re.compile(r"(?i)\b(gh|az)\s+\w")
_READ_ONLY_BASH = re.compile(
    r"(?i)^\s*("
    r"git\s+(status|diff|log|show|branch|stash\s+list|rev-parse|describe)"
    r"|ls\b|dir\b|cat\b|head\b|tail\b|rg\b|grep\b|find\b|fd\b"
    r"|pwd\b|echo\b|which\b|where\b|type\b|wc\b|file\b|stat\b|tree\b|realpath\b"
    r"|pytest\b|npm\s+test\b|cargo\s+test\b|go\s+test\b"
    r")\b"
)
_LONG_RUNNING = re.compile(r"(?i)\b(sleep\b|tail\s+-f|watch\b|while\s+true)\b")


def normalize_legacy_effect(effect: str) -> SideEffect:
    """Map serialized legacy effect names to canonical values."""
    if effect in _LEGACY_EFFECT_MAP:
        return _LEGACY_EFFECT_MAP[effect]
    return effect  # type: ignore[return-value]


def _bash_effects(command: str) -> set[SideEffect]:
    effects: set[SideEffect] = {"long_running"}
    cmd = command or ""
    if _DESTRUCTIVE_BASH.search(cmd):
        effects.add("destructive")
    if (
        _NETWORK_BASH.search(cmd)
        or _PACKAGE_INSTALL.search(cmd)
        or _GIT_NETWORK.search(cmd)
        or _CLOUD_CLI.search(cmd)
    ):
        effects.add("network")
    if _PACKAGE_INSTALL.search(cmd):
        effects.add("package_or_skill_install")
    if not _READ_ONLY_BASH.match(cmd.strip()) and not _DESTRUCTIVE_BASH.search(cmd):
        if not _NETWORK_BASH.search(cmd) and not _GIT_NETWORK.search(cmd):
            effects.add("workspace_write")
    return effects


def derive_effects(call: ToolCall) -> tuple[SideEffect, ...]:
    """Derive canonical side effects from a complete tool call."""
    name = call.name
    args = dict(call.arguments or {})
    effects: set[SideEffect] = set()

    if name in {"read", "grep", "glob", "ls", "todo_read"}:
        effects.add("workspace_read")
    elif name in {"write", "edit", "apply_patch", "todo_write"}:
        effects.add("workspace_write")
    elif name in {"web_search", "web_fetch", "webfetch", "websearch", "webcrawl", "context7_resolve", "context7_docs"}:
        effects.update({"network", "workspace_read"})
    elif name in {"task", "subagent"}:
        effects.update({"nested_agent", "long_running"})
    elif name == "skill":
        if args.get("install"):
            effects.add("package_or_skill_install")
        else:
            effects.add("workspace_read")
    elif name == "memory":
        action = str(args.get("action") or "list").lower()
        if action in {"remember", "forget"}:
            effects.add("durable_memory")
        else:
            effects.add("workspace_read")
    elif name == "bash":
        effects.update(_bash_effects(str(args.get("command") or "")))
    elif name == "memory_write":
        effects.add("durable_memory")
    else:
        effects.add("workspace_read")
        effects.add("workspace_write")

    return tuple(sorted(effects, key=str))


MANDATORY_EFFECTS: frozenset[SideEffect] = frozenset({
    "destructive",
    "network",
    "durable_memory",
    "package_or_skill_install",
    "nested_agent",
})


def tool_requires_approval_gate(tool: str, arguments: dict[str, Any]) -> bool:
    """True when a tool call must pass the approval gate (beyond policy deny)."""
    effects = set(derive_effects(ToolCall("gate", tool, arguments)))
    if effects & MANDATORY_EFFECTS:
        return True
    if "workspace_write" in effects or "long_running" in effects:
        return tool in {"write", "edit", "bash", "todo_write", "apply_patch"}
    return False


def mandatory_reason(intent_effects: tuple[SideEffect, ...], *, tool: str, args: dict[str, Any]) -> str | None:
    """Return a short reason when mandatory approval is required."""
    if "nested_agent" in intent_effects:
        return "nested agent spawn always needs approval"
    if "durable_memory" in intent_effects:
        return "durable memory changes always need approval"
    if "package_or_skill_install" in intent_effects:
        return "package or skill install always needs approval"
    if "network" in intent_effects:
        if tool == "bash":
            return "network command always needs approval"
        return "network access always needs approval"
    if "destructive" in intent_effects:
        return "destructive operation always needs approval"
    return None
