"""Injectable harness dependencies — every seam replaceable by fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from kite.application.events import EventSink, InMemoryEventSink


class Clock(Protocol):
    def now_iso(self) -> str: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str = "") -> str: ...


class ContextAssembler(Protocol):
    def build(self, run_spec: Any, sources: Any = None) -> Any: ...


class ModelGateway(Protocol):
    def complete(self, request: Any, context: Any, budget: Any) -> Any: ...

    def stream(self, request: Any, context: Any, budget: Any) -> Any: ...


class ToolExecutor(Protocol):
    def execute(self, tool_call: Any, run_context: Any) -> Any: ...


class PolicyEngine(Protocol):
    def authorize(self, tool_intent: Any) -> Any: ...


class ApprovalProvider(Protocol):
    def request(self, intent: Any) -> Any: ...


class SessionStore(Protocol):
    def load(self, session_id: str) -> Any: ...

    def save(self, session: Any) -> None: ...


class BudgetLedger(Protocol):
    def reserve(self, amount: float, reason: str) -> bool: ...

    def record(self, usage: dict[str, Any]) -> None: ...


class Verifier(Protocol):
    def consume(self, tool_result: Any) -> Any: ...


class ExecutionEnvironment(Protocol):
    def execute(self, action: dict, cwd: str = "") -> dict: ...


@dataclass
class HarnessDependencies:
    """Optional adapters; unset slots use production defaults at runtime."""

    context_assembler: ContextAssembler | None = None
    model_gateway: ModelGateway | None = None
    tool_executor: ToolExecutor | None = None
    execution_environment: ExecutionEnvironment | None = None
    policy_engine: PolicyEngine | None = None
    approval_provider: ApprovalProvider | None = None
    session_store: SessionStore | None = None
    event_sink: EventSink = field(default_factory=InMemoryEventSink)
    budget_ledger: BudgetLedger | None = None
    verifier: Verifier | None = None
    clock: Clock | None = None
    id_generator: IdGenerator | None = None
