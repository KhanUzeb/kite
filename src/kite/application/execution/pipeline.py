"""Unified tool execution pipeline."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kite.application.policy.engine import PolicyEngine
from kite.application.tools.contracts import PolicyDecision, ToolCall, ToolIntent, ToolResult


@dataclass
class ToolExecutor:
    """validate → derive intent → authorize → execute → normalize → redact."""

    policy: PolicyEngine
    runner: Callable[[ToolCall], dict[str, Any]]
    approver: Callable[[ToolIntent, PolicyDecision], bool] | None = None
    redactor: Callable[[str], str] | None = None

    def execute(self, call: ToolCall, run_context: dict[str, Any] | None = None) -> ToolResult:
        run_context = run_context or {}
        intent = self.policy.derive_intent(call)
        decision = self.policy.authorize(intent)
        if not decision.allowed:
            return ToolResult(
                call_id=call.call_id,
                status="denied",
                ok=False,
                error=decision.reason,
                policy_decision=decision,
            )
        if decision.requires_approval and self.approver and not self.approver(intent, decision):
            return ToolResult(
                call_id=call.call_id,
                status="denied",
                ok=False,
                error="approval denied",
                policy_decision=decision,
            )
        start = time.monotonic()
        try:
            raw = self.runner(call)
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                status="error",
                ok=False,
                error=str(exc),
                duration=time.monotonic() - start,
                policy_decision=decision,
            )
        output = str(raw.get("output", ""))
        if self.redactor:
            output = self.redactor(output)
        changed = tuple(str(p) for p in raw.get("changed_paths") or ())
        return ToolResult(
            call_id=call.call_id,
            status="ok" if raw.get("ok", True) else "error",
            ok=bool(raw.get("ok", True)),
            output=output,
            error=str(raw.get("error", "")),
            changed_paths=changed,
            duration=time.monotonic() - start,
            policy_decision=decision,
            metadata={"run_context": run_context},
        )
