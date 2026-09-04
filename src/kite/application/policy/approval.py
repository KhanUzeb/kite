"""Approval request/decision coordination — single terminal input owner."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Decision = Literal["allow", "session", "always", "deny", "stop"]


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: str
    tool: str
    arguments: dict[str, Any]
    reason: str
    mandatory: bool
    diff: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalCoordinator:
    """Worker blocks on request(); main thread resolves via resolve()."""

    interactive: bool = True
    timeout_seconds: float = 600.0
    wake_main: Callable[[], None] | None = None
    _pending: ApprovalRequest | None = field(default=None, init=False)
    _decision: Decision | None = field(default=None, init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def pending(self) -> ApprovalRequest | None:
        with self._lock:
            return self._pending

    def request(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        reason: str = "",
        mandatory: bool = False,
        diff: str = "",
        extra: dict[str, Any] | None = None,
    ) -> Decision:
        if not self.interactive:
            return "deny" if mandatory else "allow"
        req = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            tool=tool,
            arguments=dict(arguments),
            reason=reason,
            mandatory=mandatory,
            diff=diff,
            extra=dict(extra or {}),
        )
        with self._lock:
            self._pending = req
            self._decision = None
            self._ready.clear()
        if self.wake_main is not None:
            try:
                self.wake_main()
            except Exception:
                pass
        if not self._ready.wait(timeout=self.timeout_seconds):
            return "deny"
        with self._lock:
            return self._decision or "deny"

    def resolve(self, decision: Decision) -> bool:
        with self._lock:
            if self._pending is None:
                return False
            self._decision = decision
            self._pending = None
            self._ready.set()
        return True


def child_inherits_parent_policy(
    *,
    parent_approval: str,
    parent_mode: str,
    parent_no_guardrails: bool,
    parent_execution_mode: str | None,
    child_overrides: dict[str, Any] | None = None,
) -> dict[str, str | bool]:
    """Nested agents inherit parent policy — elevation attempts are rejected."""
    overrides = dict(child_overrides or {})
    child_approval = str(overrides.get("approval") or parent_approval)
    if child_approval == "yolo" and parent_approval != "yolo":
        child_approval = parent_approval
    child_guardrails = bool(parent_no_guardrails)
    if overrides.get("no_guardrails") and not parent_no_guardrails:
        child_guardrails = False
    return {
        "approval": child_approval,
        "mode": str(overrides.get("mode") or parent_mode),
        "no_guardrails": child_guardrails,
        "execution_mode": str(overrides.get("execution_mode") or parent_execution_mode or "restricted"),
    }
