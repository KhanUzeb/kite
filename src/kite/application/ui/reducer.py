"""REPL event reducer — UI state as projection of canonical events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kite.application.events import EventEnvelope


@dataclass
class ReplPresentation:
    status: str = "idle"
    last_message: str = ""
    tool_active: str = ""
    cost: float = 0.0
    turn: int = 0
    errors: list[str] = field(default_factory=list)


class ReplEventReducer:
    """Reduce EventEnvelope stream into presentation model."""

    def __init__(self) -> None:
        self.presentation = ReplPresentation()
        self._events: list[EventEnvelope] = []

    def apply(self, envelope: EventEnvelope) -> ReplPresentation:
        self._events.append(envelope)
        kind = envelope.kind
        payload = envelope.payload
        if kind == "agent_start":
            self.presentation.status = "running"
        elif kind == "agent_end":
            self.presentation.status = str(payload.get("exit_status", "done")).lower()
        elif kind == "turn_start":
            self.presentation.turn = int(payload.get("n", self.presentation.turn + 1))
        elif kind == "stream_delta":
            self.presentation.last_message += str(payload.get("text", ""))
        elif kind == "tool_start":
            self.presentation.tool_active = str(payload.get("tool", ""))
        elif kind == "tool_end":
            self.presentation.tool_active = ""
        elif kind == "cost":
            self.presentation.cost = float(payload.get("cost", self.presentation.cost))
        elif kind == "error":
            self.presentation.errors.append(str(payload.get("message", payload)))
        return self.presentation

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.presentation.status,
            "turn": self.presentation.turn,
            "cost": self.presentation.cost,
            "tool_active": self.presentation.tool_active,
            "event_count": len(self._events),
        }
