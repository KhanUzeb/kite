"""Explicit run state machine for harness orchestration."""

from __future__ import annotations

from kite.application.contracts import RunStatus

TERMINAL_STATES: frozenset[RunStatus] = frozenset(
    {"completed", "failed", "cancelled"},
)

VALID_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    "created": frozenset({"prepared", "failed", "cancelled"}),
    "prepared": frozenset({"awaiting_model", "failed", "cancelled"}),
    "awaiting_model": frozenset(
        {"awaiting_approval", "executing_tools", "observing", "compacting", "completed", "failed", "cancelled"},
    ),
    "awaiting_approval": frozenset({"executing_tools", "failed", "cancelled"}),
    "executing_tools": frozenset({"observing", "failed", "cancelled"}),
    "observing": frozenset(
        {"awaiting_model", "compacting", "completed", "failed", "cancelled"},
    ),
    "compacting": frozenset({"awaiting_model", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def can_transition(from_state: RunStatus, to_state: RunStatus) -> bool:
    if from_state == to_state:
        return True
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


class RunState:
    """Mutable run state with validated transitions."""

    __slots__ = ("_state",)

    def __init__(self, initial: RunStatus = "created") -> None:
        self._state = initial

    @property
    def value(self) -> RunStatus:
        return self._state

    @property
    def terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def transition(self, next_state: RunStatus) -> RunStatus:
        if not can_transition(self._state, next_state):
            raise ValueError(f"invalid run transition: {self._state} -> {next_state}")
        self._state = next_state
        return self._state
