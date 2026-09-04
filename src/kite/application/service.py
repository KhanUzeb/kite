"""Application run service — canonical entry for harness execution."""

from __future__ import annotations

import uuid
from typing import Any

from kite.agent.harness import Harness
from kite.application.adapters.harness import harness_config_from_run_spec
from kite.application.contracts import RunResult, RunSpec, StopReason
from kite.application.dependencies import HarnessDependencies
from kite.application.events import LegacyEventBridge
from kite.application.state import RunState


def _map_exit_status(exit_status: str | None) -> tuple[str, StopReason | None]:
    status = (exit_status or "").strip()
    mapping: dict[str, tuple[str, StopReason]] = {
        "Submitted": ("completed", "submitted"),
        "Error": ("failed", "error"),
        "Cancelled": ("cancelled", "cancelled"),
        "LimitsExceeded": ("failed", "limits_exceeded"),
        "Stalled": ("failed", "stalled"),
        "Interrupted": ("cancelled", "interrupted"),
    }
    if status in mapping:
        return mapping[status]
    if status:
        return "failed", "error"
    return "completed", None


class ApplicationRunService:
    """Execute runs through the legacy harness while emitting canonical events."""

    def run(
        self,
        spec: RunSpec,
        deps: HarnessDependencies | None = None,
        *,
        harness: Harness | None = None,
        cancel: Any = None,
    ) -> RunResult:
        deps = deps or HarnessDependencies()
        run_id = spec.run_id or str(uuid.uuid4())
        state = RunState("created")
        state.transition("prepared")

        bridge = LegacyEventBridge(run_id=run_id, sink=deps.event_sink)
        config = harness_config_from_run_spec(spec)
        h = harness or Harness(config=config)
        if harness is not None:
            h.config = config

        unsubscribe = h.subscribe(bridge.wrap_listener())
        state.transition("awaiting_model")

        try:
            legacy = h.run(spec.task, cancel=cancel)
        finally:
            unsubscribe()

        exit_status = str(legacy.get("exit_status") or "")
        run_status, stop_reason = _map_exit_status(exit_status)
        state.transition(run_status)

        submission = str(legacy.get("submission") or "")
        cost = float(legacy.get("cost") or legacy.get("usage", {}).get("cost", 0) or 0)
        verification = dict(legacy.get("verification") or {})
        usage = dict(legacy.get("usage") or {})
        if cost and "cost" not in usage:
            usage["cost"] = cost

        changed = tuple(str(p) for p in legacy.get("changed_paths") or ())
        verification_status = str(
            legacy.get("verification_status")
            or verification.get("status")
            or ""
        )
        evidence_summary = dict(verification) if verification else {}
        approval_reason = str(legacy.get("approval_reason") or legacy.get("blocked_reason") or "")
        blocked_reason = str(legacy.get("submit_blocked") or legacy.get("blocked_reason") or "")

        return RunResult(
            status=state.value,
            stop_reason=stop_reason,
            final_message=submission,
            verification=verification,
            verification_status=verification_status,
            evidence_summary=evidence_summary,
            approval_reason=approval_reason,
            blocked_reason=blocked_reason,
            usage=usage,
            cost=cost,
            changed_paths=changed,
            context_snapshot_id=legacy.get("context_snapshot_id"),
            trace_id=run_id,
            legacy=legacy,
        )
