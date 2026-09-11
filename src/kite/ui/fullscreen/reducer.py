"""Reduce agent events into a fluid fullscreen view model."""

from __future__ import annotations

import time
import uuid
from typing import Any

from kite.agent.events import Event
from kite.application.events import EventEnvelope
from kite.ui.fullscreen.model import (
    AgentWorker,
    ChangeFile,
    FullscreenModel,
    StreamLine,
    VerificationCheck,
)
from kite.ui.tool_cards import detail_from_args


class FullscreenReducer:
    """Event log is truth; ``FullscreenModel`` is a projection."""

    def __init__(self, *, run_id: str = "") -> None:
        self.model = FullscreenModel(run_id=run_id or str(uuid.uuid4()))
        self._sequence = 0
        self._tool_lines: dict[str, str] = {}
        self._tool_starts: dict[str, float] = {}

    def apply_event(self, event: Event) -> FullscreenModel:
        return self._apply(event.kind, dict(event.payload))

    def apply_envelope(self, envelope: EventEnvelope) -> FullscreenModel:
        return self._apply(envelope.kind, dict(envelope.payload), sequence=envelope.sequence)

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
        cost: float | None = None,
        turn: int | None = None,
        plan_done: int = 0,
        plan_total: int = 0,
        display_mode: str | None = None,
    ) -> FullscreenModel:
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
        self.model.composer.queued = queued
        if context_pct:
            self.model.context_pct = context_pct
        if cost is not None:
            self.model.cost = cost
        if turn is not None:
            self.model.turn = turn
        self.model.plan_done = plan_done
        self.model.plan_total = plan_total
        if display_mode in {"compact", "fullscreen"}:
            self.model.display_mode = display_mode  # type: ignore[assignment]
        return self.model

    def _push_stream(
        self,
        *,
        line_id: str,
        mark: str,
        label: str,
        detail: str = "",
        status: str = "ok",
    ) -> None:
        self.model.stream.append(
            StreamLine(id=line_id, mark=mark, label=label, detail=detail, status=status)
        )
        if len(self.model.stream) > 80:
            self.model.stream = self.model.stream[-80:]

    def _update_stream(self, line_id: str, *, mark: str, status: str, detail: str = "") -> None:
        for line in reversed(self.model.stream):
            if line.id == line_id:
                line.mark = mark
                line.status = status
                if detail:
                    line.detail = detail
                return

    def _apply(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        sequence: int | None = None,
    ) -> FullscreenModel:
        self._sequence = sequence if sequence is not None else self._sequence + 1
        seq = self._sequence

        if kind == "agent_start":
            self.model.status = "running"
            task = str(payload.get("task") or "").strip()
            if task:
                preview = task.splitlines()[0][:72]
                self._push_stream(
                    line_id=f"task:{seq}",
                    mark="›",
                    label="task",
                    detail=preview,
                    status="ok",
                )
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
            args = payload.get("arguments") or {}
            self.model.active_tool = tool
            key = f"{tool}:{payload.get('call_id') or seq}"
            self._tool_starts[key] = time.monotonic()
            self._tool_lines[tool] = key
            detail = detail_from_args(tool, args)[:64]
            self._push_stream(
                line_id=key,
                mark="●",
                label=tool,
                detail=detail,
                status="running",
            )
        elif kind == "tool_end":
            tool = str(payload.get("tool") or "")
            key = self._tool_lines.get(tool, f"{tool}:{seq}")
            ok = payload.get("ok", True)
            mark = "✓" if ok else "✗"
            status = "ok" if ok else "failed"
            err = str(payload.get("error") or "")
            detail = err.splitlines()[0][:64] if err and not ok else ""
            self._update_stream(key, mark=mark, status=status, detail=detail)
            if tool == self.model.active_tool:
                self.model.active_tool = ""
        elif kind == "stream_delta":
            text = str(payload.get("text") or "")
            if not text.strip():
                return self.model
            preview = " ".join(text.split())[:72]
            if self.model.stream and self.model.stream[-1].label == "assistant":
                self.model.stream[-1].detail = preview
            else:
                self._push_stream(
                    line_id=f"assistant:{seq}",
                    mark="•",
                    label="assistant",
                    detail=preview,
                    status="running",
                )
        elif kind == "diff":
            path = str(payload.get("path") or "")
            if not path:
                return self.model
            added = int(payload.get("added") or 0)
            deleted = int(payload.get("deleted") or 0)
            existing = next((f for f in self.model.review.files if f.path == path), None)
            if existing:
                existing.added = added
                existing.deleted = deleted
            else:
                self.model.review.files.append(ChangeFile(path=path, added=added, deleted=deleted))
            self.model.review.total_added = sum(f.added for f in self.model.review.files)
            self.model.review.total_deleted = sum(f.deleted for f in self.model.review.files)
        elif kind == "verification_status":
            label = str(payload.get("status") or "unverified")
            self.model.review.verification_label = label
            self.model.review.verified = label in {"verified", "idle"}
        elif kind == "verification_record":
            name = str(payload.get("name") or payload.get("kind") or "check")
            ok = bool(payload.get("ok", True))
            summary = str(payload.get("output_summary") or payload.get("message") or "")
            self.model.verification_checks.append(
                VerificationCheck(
                    name=name[:16],
                    status="pass" if ok else "fail",
                    summary=summary[:48],
                )
            )
            if len(self.model.verification_checks) > 12:
                self.model.verification_checks = self.model.verification_checks[-12:]
        elif kind == "approval":
            action = str(payload.get("action") or "")
            if action == "request":
                self.model.approval.active = True
                self.model.approval.tool = str(payload.get("tool") or "")
                self.model.approval.summary = str(payload.get("reason") or payload.get("summary") or "")
                self.model.approval.mandatory = bool(payload.get("mandatory"))
            elif action in {"allow", "deny", "resolve"}:
                self.model.approval.active = False
        elif kind == "todo":
            items = payload.get("items") or []
            self.model.plan_total = len(items)
            self.model.plan_done = sum(1 for item in items if item.get("status") == "completed")
        elif kind == "subagent_start":
            label = str(payload.get("label") or payload.get("profile") or "worker")
            self.model.agents.append(AgentWorker(name=label[:16], status="running"))
        elif kind == "subagent_end":
            label = str(payload.get("label") or payload.get("profile") or "")
            for worker in reversed(self.model.agents):
                if worker.name == label[:16] or not label:
                    worker.status = "completed"
                    break
        elif kind == "error":
            msg = str(payload.get("message") or payload)
            self.model.errors.append(msg[:120])
            if len(self.model.errors) > 6:
                self.model.errors = self.model.errors[-6:]
        elif kind == "cost":
            self.model.cost = float(payload.get("cost", self.model.cost))
        elif kind == "submit_blocked":
            reason = str(payload.get("reason") or "submit blocked")
            self.model.errors.append(reason[:120])
            self.model.status = "blocked"

        return self.model
