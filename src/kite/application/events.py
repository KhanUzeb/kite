"""Canonical event envelopes — sequenced, identified lifecycle records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from kite.agent.events import Event, EventKind

SCHEMA_VERSION = 1
REDACTION_VERSION = 1


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    run_id: str
    parent_event_id: str | None
    sequence: int
    timestamp: str
    kind: EventKind
    payload: dict[str, Any]
    schema_version: int = SCHEMA_VERSION
    redaction_version: int = REDACTION_VERSION


class EventSink(Protocol):
    def append(self, envelope: EventEnvelope) -> None: ...

    def load_run(self, run_id: str) -> list[EventEnvelope]: ...


class InMemoryEventSink:
    """Test-friendly event store."""

    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []
        self._by_run: dict[str, list[EventEnvelope]] = {}

    def append(self, envelope: EventEnvelope) -> None:
        self._events.append(envelope)
        self._by_run.setdefault(envelope.run_id, []).append(envelope)

    def load_run(self, run_id: str) -> list[EventEnvelope]:
        return list(self._by_run.get(run_id, []))

    def all(self) -> list[EventEnvelope]:
        return list(self._events)


class EventSequencer:
    """Assign monotonic sequence numbers and event IDs."""

    __slots__ = ("_run_id", "_next", "_parent_stack")

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._next = 0
        self._parent_stack: list[str] = []

    @property
    def run_id(self) -> str:
        return self._run_id

    def emit(self, kind: EventKind, payload: dict[str, Any] | None = None) -> EventEnvelope:
        self._next += 1
        event_id = str(uuid.uuid4())
        parent = self._parent_stack[-1] if self._parent_stack else None
        envelope = EventEnvelope(
            event_id=event_id,
            run_id=self._run_id,
            parent_event_id=parent,
            sequence=self._next,
            timestamp=datetime.now(UTC).isoformat(),
            kind=kind,
            payload=dict(payload or {}),
        )
        return envelope

    def push_parent(self, event_id: str) -> None:
        self._parent_stack.append(event_id)

    def pop_parent(self) -> None:
        if self._parent_stack:
            self._parent_stack.pop()


def envelope_from_legacy(
    event: Event,
    *,
    run_id: str,
    sequencer: EventSequencer,
) -> EventEnvelope:
    """Wrap a legacy ``Event`` as a canonical ``EventEnvelope``."""
    return sequencer.emit(event.kind, event.payload)


def legacy_from_envelope(envelope: EventEnvelope) -> Event:
    """Project a canonical envelope back to the legacy event type."""
    return Event(kind=envelope.kind, payload=dict(envelope.payload))


class LegacyEventBridge:
    """Subscribe to legacy events and emit canonical envelopes."""

    def __init__(self, run_id: str, sink: EventSink) -> None:
        self.run_id = run_id
        self.sink = sink
        self._sequencer = EventSequencer(run_id)
        self._unsubscribe: Any = None

    def wrap_listener(self, legacy_listener: Any | None = None) -> Any:
        def _listener(event: Event) -> None:
            envelope = self._sequencer.emit(event.kind, event.payload)
            self.sink.append(envelope)
            if legacy_listener is not None:
                legacy_listener(event)

        return _listener
