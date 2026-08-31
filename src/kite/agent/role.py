"""Multi-agent role separation — architect / implementer / debugger personas."""

from __future__ import annotations

from enum import Enum

from kite.agent.mode import BUILD_TOOLS, PLAN_TOOLS, READONLY_TOOLS, filter_enabled


class AgentRole(str, Enum):
    AUTO = "auto"  # infer from mode
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    DEBUGGER = "debugger"


# Role → allowed tools (subset of full catalog)
ROLE_TOOLS: dict[AgentRole, frozenset[str]] = {
    AgentRole.AUTO: BUILD_TOOLS,
    AgentRole.ARCHITECT: frozenset({*PLAN_TOOLS}),
    AgentRole.IMPLEMENTER: frozenset({*BUILD_TOOLS}),
    AgentRole.DEBUGGER: frozenset(
        {"read", "grep", "glob", "ls", "bash", "task", "webfetch", "websearch", "webcrawl", "skill", "memory", "todo_read"}
    ),
}


def parse_role(raw: str | None, *, mode: str = "build") -> AgentRole:
    text = (raw or "auto").strip().lower()
    aliases = {"implement": "implementer", "debug": "debugger", "plan": "architect"}
    text = aliases.get(text, text)
    try:
        role = AgentRole(text)
    except ValueError:
        role = AgentRole.AUTO
    if role is AgentRole.AUTO:
        return AgentRole.ARCHITECT if mode == "plan" else AgentRole.IMPLEMENTER
    return role


def tools_for_role(role: AgentRole, enabled: list[str]) -> list[str]:
    allow = ROLE_TOOLS.get(role, BUILD_TOOLS)
    return filter_enabled(enabled, allow)
