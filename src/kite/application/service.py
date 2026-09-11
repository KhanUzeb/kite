"""Application run service — canonical entry for harness execution."""

from __future__ import annotations

import uuid
from typing import Any

from kite.agent.events import Event
from kite.agent.harness import Harness
from kite.application.adapters import harness_config_from_run_spec
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
        "TimeExceeded": ("failed", "limits_exceeded"),
        "Stalled": ("failed", "stalled"),
        "Interrupted": ("cancelled", "interrupted"),
        "ProviderFault": ("failed", "error"),
    }
    if status in mapping:
        return mapping[status]
    return "failed", "error"


def _apply_run_state(state: RunState, event: Event) -> None:
    kind = event.kind
    current = state.value
    if current in {"completed", "failed", "cancelled"}:
        return
    if kind in {"agent_start", "turn_start"}:
        if current in {"prepared", "observing", "compacting", "executing_tools"}:
            state.transition("awaiting_model")
    elif kind == "compaction_start":
        if current in {"awaiting_model", "observing"}:
            state.transition("compacting")
    elif kind in {"compact", "compaction_end"}:
        if current == "compacting":
            state.transition("awaiting_model")
    elif kind == "approval":
        if current == "awaiting_model":
            state.transition("awaiting_approval")
    elif kind == "tool_start":
        if current in {"awaiting_model", "awaiting_approval"}:
            state.transition("executing_tools")
    elif kind == "tool_end":
        if current == "executing_tools":
            state.transition("observing")
    elif kind == "turn_end":
        if current in {"awaiting_model", "executing_tools", "observing"}:
            state.transition("observing")


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
        if harness is not None:
            # Spec was built from this harness in execute_harness_task — keep wired
            # fields (memory_in_prompt, session wiring) instead of replacing config.
            h = harness
        else:
            h = Harness(config=harness_config_from_run_spec(spec))
        if deps.tool_executor is not None:
            h.tool_executor = deps.tool_executor
        if deps.policy_engine is not None:
            h.policy_engine = deps.policy_engine

        def _state_listener(event: Event) -> None:
            _apply_run_state(state, event)

        unsubscribe = h.subscribe(bridge.wrap_listener(_state_listener))
        state.transition("awaiting_model")

        try:
            legacy = h.run(spec.task, cancel=cancel)
        finally:
            unsubscribe()

        exit_status = str(legacy.get("exit_status") or "")
        run_status, stop_reason = _map_exit_status(exit_status)
        if run_status != state.value:
            state.transition(run_status)
        return _build_run_result(state.value, stop_reason, run_id, legacy)


def _build_run_result(
    status: str,
    stop_reason: StopReason | None,
    run_id: str,
    legacy: dict[str, Any],
) -> RunResult:
    submission = str(legacy.get("submission") or "")
    cost = float(legacy.get("cost") or legacy.get("usage", {}).get("cost", 0) or 0)
    verification = dict(legacy.get("verification") or {})
    usage = dict(legacy.get("usage") or {})
    if cost and "cost" not in usage:
        usage["cost"] = cost

    changed = tuple(str(p) for p in legacy.get("changed_paths") or ())
    verification_status = str(legacy.get("verification_status") or verification.get("status") or "")
    evidence_summary = dict(verification) if verification else {}
    approval_reason = str(legacy.get("approval_reason") or legacy.get("blocked_reason") or "")
    blocked_reason = str(legacy.get("submit_blocked") or legacy.get("blocked_reason") or "")

    return RunResult(
        status=status,
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
