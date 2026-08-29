"""Thin event types — frontends subscribe; core never renders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal[
    "agent_start",
    "agent_end",
    "turn_start",
    "turn_end",
    "message",
    "stream_start",
    "stream_reasoning",
    "stream_delta",
    "stream_tool",
    "stream_end",
    "tool_start",
    "tool_end",
    "context",
    "compact",
    "error",
    "approval",
    "todo",
    "diff",
    "interrupt",
    "mode",
    "cost",
    "commit",
    "route",
    "attach",
    "loop_warning",
    "artifact",
    "cost_estimate",
    "cost_warning",
    "subagent_start",
    "subagent_end",
]


@dataclass(slots=True)
class Event:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
