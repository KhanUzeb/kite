"""Application-layer contracts for Kite 0.9 harness orchestration."""

from kite.application.contracts import (
    ModelSelection,
    RunLimits,
    RunResult,
    RunSpec,
    RunStatus,
    StopReason,
)
from kite.application.dependencies import HarnessDependencies
from kite.application.events import EventEnvelope, EventSink, InMemoryEventSink
from kite.application.state import RunState

__all__ = [
    "ApplicationRunService",
    "EventEnvelope",
    "EventSink",
    "HarnessDependencies",
    "InMemoryEventSink",
    "ModelSelection",
    "RunLimits",
    "RunResult",
    "RunSpec",
    "RunState",
    "RunStatus",
    "StopReason",
]


def __getattr__(name: str):
    if name == "ApplicationRunService":
        from kite.application.service import ApplicationRunService

        return ApplicationRunService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
