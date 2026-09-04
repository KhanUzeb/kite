"""Injectable harness dependencies — every seam replaceable by fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kite.application.events import EventSink, InMemoryEventSink


@dataclass
class HarnessDependencies:
    """Optional adapters; unset slots use production defaults at runtime."""

    event_sink: EventSink = field(default_factory=InMemoryEventSink)
    context_assembler: Any = None
    model_gateway: Any = None
    tool_executor: Any = None
    execution_environment: Any = None
    policy_engine: Any = None
    approval_provider: Any = None
    session_store: Any = None
    budget_ledger: Any = None
    verifier: Any = None
    clock: Any = None
    id_generator: Any = None
