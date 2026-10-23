"""Injectable harness dependencies — every seam replaceable by fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kite.application.events import EventSink, InMemoryEventSink


@dataclass
class HarnessDependencies:
    """Optional adapters; unset slots use production defaults at runtime."""

    event_sink: EventSink = field(default_factory=InMemoryEventSink)
    tool_executor: Any = None
    policy_engine: Any = None
