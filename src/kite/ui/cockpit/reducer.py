"""Reduce event streams into a run-centric view model."""

from __future__ import annotations

import time
import uuid
from typing import Any

from kite.agent.events import Event
from kite.application.events import EventEnvelope
from kite.ui.cockpit.timeline import make_timeline_entry
from kite.ui.cockpit.view_model import (
    AgentWorker,
    ChangeFile,
    RunViewModel,
    TimelineEntry,
    VerificationCheck,
)


class RunCockpitReducer:
    """Event log is truth; ``RunViewModel`` is a projection."""

    def __init__(self, *, run_id: str = "") -> None:
        self.model = RunViewModel(run_id=run_id or str(uuid.uuid4()))
        self._sequence = 0
        self._tool_starts: dict[str, float] = {}
        self._tool_keys: dict[str, str] = {}
        self._pending_tools: list[str] = []

    def apply_event(self, event: Event) -> RunViewModel:
        return self._apply(event.kind, dict(event.payload))

    def apply_envelope(self, envelope: EventEnvelope) -> RunViewModel:
        return self._apply(envelope.kind, dict(envelope.payload), timestamp=envelope.timestamp, sequence=envelope.sequence)

    def sync_session(
        self,
        *,
        mode: str = "",
        provider: str = "",
        model: str = "",
        branch: str = "",
        repo: str = "",
        approval: str = "",
        attachments: list[str] | None = None,
        queued: int = 0,
        context_pct: float = 0.0,
        context_files: int = 0,
        window: int = 0,
        tokens: int = 0,
        cost: float | None = None,
        turn: int | None = None,
        display_mode: str | None = None,
    ) -> RunViewModel:
        if mode:
            self.model.mode = mode
            self.model.composer.mode = mode
        if provider:
            self.model.provider = provider
            self.model.composer.provider = provider
        if model:
            self.model.model = model
            self.model.composer.model = model
        if branch:
            self.model.branch = branch
        if repo:
            self.model.repo = repo
        if approval:
            self.model.composer.approval = approval
        if attachments is not None:
            self.model.composer.attachments = list(attachments)
        if queued is not None:
            self.model.composer.queued = queued
        if context_pct:
            self.model.context.pct = context_pct
        if context_files:
            self.model.context.files = context_files
        if window:
            self.model.context.window = window
        if tokens:
            self.model.context.tokens = tokens
        if cost is not None:
            self.model.cost = cost
        if turn is not None:
            self.model.turn = turn
        if display_mode in {"compact", "cockpit"}:
            self.model.display_mode = display_mode  # type: ignore[assignment]
        return self.model

    def _apply(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        timestamp: str = "",
        sequence: int | None = None,
    ) -> RunViewModel:
        self._sequence = sequence if sequence is not None else self._sequence + 1
        seq = self._sequence

        if kind == "agent_start":
            self.model.status = "running"
            task = str(payload.get("task") or "")
            if task:
                self.model.goal = task
        elif kind == "agent_end":
            self.model.status = str(payload.get("exit_status") or "done").lower()
            self.model.active_tool = ""
        elif kind == "turn_start":
            self.model.turn = int(payload.get("n", self.model.turn + 1))
            self.model.status = "running"
        elif kind == "turn_end":
            self.model.active_tool = ""
        elif kind == "tool_start":
            tool = str(payload.get("tool") or "")
            self.model.active_tool = tool
            key = f"{tool}:{payload.get('call_id') or seq}"
            self._tool_starts[key] = time.monotonic()
            self._tool_keys[tool] = key
            self._pending_tools.append(tool)
        elif kind == "tool_end":
            tool = str(payload.get("tool") or "")
            if self.model.active_tool == tool:
                self.model.active_tool = ""
            duration_ms = self._pop_tool_duration(tool)
            self._record_change(payload, tool)
        elif kind == "diff":
            self._record_change(payload, str(payload.get("tool") or "edit"))
        elif kind == "todo":
            self._update_plan(payload)
        elif kind == "approval":
            self._on_approval(payload)
        elif kind == "verification_status":
            status = str(payload.get("status") or "")
            self.model.review.verification_label = status or "unverified"
            self.model.review.verified = status == "verified"
            self._push_verification_check("status", status, payload)
        elif kind == "verification_plan":
            plan = payload.get("plan") or payload
            checks = plan.get("required_checks") if isinstance(plan, dict) else None
            if isinstance(checks, list):
                for check in checks:
                    if isinstance(check, dict):
                        self._push_verification_check(
                            str(check.get("kind") or "check"),
                            "pending",
                            check,
                        )
        elif kind == "verification_record":
            ok = bool(payload.get("ok", True))
            name = str(payload.get("kind") or payload.get("check") or "verification")
            self._push_verification_check(name, "pass" if ok else "fail", payload)
            self.model.review.verified = ok and self.model.review.verified
        elif kind == "submit_blocked":
            self.model.status = "blocked"
            reason = str(payload.get("reason") or "submit blocked")
            self.model.errors.append(reason)
            self.model.review.verified = False
            self.model.review.verification_label = "unverified"
        elif kind == "context":
            self.model.context.pct = float(payload.get("pct") or payload.get("ratio", 0) * 100)
            self.model.context.window = int(payload.get("window") or self.model.context.window)
            self.model.context.tokens = int(payload.get("total_tokens") or payload.get("tokens") or self.model.context.tokens)
        elif kind == "cost":
            self.model.cost = float(payload.get("cost", self.model.cost))
        elif kind == "error":
            self.model.errors.append(str(payload.get("message") or payload))
        elif kind == "subagent_start":
            name = str(payload.get("name") or payload.get("profile") or "subagent")
            self.model.agents.workers.append(
                AgentWorker(name=name, status="running", objective=str(payload.get("task") or ""))
            )
        elif kind == "subagent_end":
            name = str(payload.get("name") or payload.get("profile") or "")
            for worker in reversed(self.model.agents.workers):
                if worker.name == name or not name:
                    worker.status = "completed" if payload.get("ok", True) else "failed"
                    break
        elif kind == "job_start":
            jid = str(payload.get("id") or payload.get("job_id") or "job")
            self.model.agents.workers.append(AgentWorker(name=jid, status="running"))
        elif kind == "job_end":
            jid = str(payload.get("id") or payload.get("job_id") or "")
            for worker in reversed(self.model.agents.workers):
                if worker.name == jid or not jid:
                    worker.status = "completed" if payload.get("ok", True) else "failed"
                    break

        entry = make_timeline_entry(
            entry_id=f"{seq}:{kind}",
            kind=kind,
            payload=payload,
            sequence=seq,
            timestamp=timestamp,
            duration_ms=self._last_duration_ms if kind == "tool_end" else None,
        )
        if entry is not None:
            self._merge_timeline(entry, kind)

        return self.model

    _last_duration_ms: int | None = None

    def _pop_tool_duration(self, tool: str) -> int | None:
        key = self._tool_keys.pop(tool, None)
        if key is None:
            self._last_duration_ms = None
            return None
        started = self._tool_starts.pop(key, None)
        if started is None:
            self._last_duration_ms = None
            return None
        ms = int((time.monotonic() - started) * 1000)
        self._last_duration_ms = ms
        return ms

    def _record_change(self, payload: dict[str, Any], tool: str) -> None:
        path = str(payload.get("path") or "")
        if not path and tool not in {"write", "edit"}:
            return
        added = int(payload.get("added") or payload.get("lines_added") or 0)
        deleted = int(payload.get("deleted") or payload.get("lines_deleted") or 0)
        diff = payload.get("diff")
        if isinstance(diff, str) and diff and not (added or deleted):
            from kite.ui.diff import count_diff_lines

            added, deleted = count_diff_lines(diff)
        if not path:
            return
        for existing in self.model.review.files:
            if existing.path == path:
                existing.added += added
                existing.deleted += deleted
                self._recompute_review_totals()
                return
        self.model.review.files.append(ChangeFile(path=path, added=added, deleted=deleted))
        self._recompute_review_totals()

    def _recompute_review_totals(self) -> None:
        self.model.review.total_added = sum(f.added for f in self.model.review.files)
        self.model.review.total_deleted = sum(f.deleted for f in self.model.review.files)

    def _update_plan(self, payload: dict[str, Any]) -> None:
        items = payload.get("todos") or payload.get("items")
        if isinstance(items, list):
            self.model.plan_total = len(items)
            self.model.plan_done = sum(1 for i in items if str(i.get("status", "")) == "completed")
            return
        status = str(payload.get("status") or "")
        if status == "completed":
            self.model.plan_done += 1
        self.model.plan_total = max(self.model.plan_total, self.model.plan_done)

    def _on_approval(self, payload: dict[str, Any]) -> None:
        phase = str(payload.get("phase") or "")
        if phase == "request" or payload.get("awaiting"):
            self.model.approval.active = True
            self.model.approval.tool = str(payload.get("tool") or "")
            self.model.approval.summary = str(payload.get("summary") or payload.get("reason") or "")
            self.model.approval.risk = str(payload.get("risk") or payload.get("tier") or "")
            self.model.approval.scope = str(payload.get("scope") or "")
            self.model.approval.mandatory = bool(payload.get("mandatory"))
            self.model.status = "awaiting_approval"
        else:
            self.model.approval.active = False
            if self.model.status == "awaiting_approval":
                self.model.status = "running"

    def _push_verification_check(self, name: str, status: str, payload: dict[str, Any]) -> None:
        summary = str(payload.get("output_summary") or payload.get("summary") or "")
        for check in self.model.verification_checks:
            if check.name == name:
                check.status = status
                if summary:
                    check.summary = summary
                return
        self.model.verification_checks.append(VerificationCheck(name=name, status=status, summary=summary))

    def _merge_timeline(self, entry: TimelineEntry, raw_kind: str) -> None:
        if entry.kind == "tool" and raw_kind == "tool_end":
            for existing in reversed(self.model.timeline):
                if existing.kind == "tool" and existing.tool == entry.tool and existing.status == "running":
                    existing.status = entry.status
                    existing.duration_ms = entry.duration_ms
                    if entry.detail:
                        existing.detail = entry.detail
                    existing.affected_files = entry.affected_files
                    return
        if entry.kind == "plan" and raw_kind == "todo":
            for existing in reversed(self.model.timeline):
                if existing.kind == "plan" and existing.title == entry.title:
                    existing.status = entry.status
                    return
        self.model.timeline.append(entry)
