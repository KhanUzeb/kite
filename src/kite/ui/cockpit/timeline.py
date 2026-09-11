"""Map harness events to semantic timeline entries."""

from __future__ import annotations

from typing import Any

from kite.ui.cockpit.view_model import TimelineEntry, TimelineKind, TimelineStatus

_KIND_FOR_EVENT: dict[str, TimelineKind] = {
    "agent_start": "goal",
    "todo": "plan",
    "stream_reasoning": "reason",
    "tool_start": "tool",
    "tool_end": "tool",
    "diff": "change",
    "approval": "approval",
    "verification_status": "verification",
    "verification_plan": "verification",
    "verification_record": "verification",
    "checkpoint": "checkpoint",
    "handoff": "handoff",
    "agent_end": "result",
    "submit_blocked": "verification",
    "error": "error",
    "compact": "checkpoint",
    "subagent_start": "tool",
    "subagent_end": "tool",
    "job_start": "tool",
    "job_end": "tool",
}


def timeline_kind_for_event(kind: str, payload: dict[str, Any] | None = None) -> TimelineKind | None:
    p = payload or {}
    if kind == "tool_end" and (p.get("diff") or p.get("tool") in {"write", "edit"}):
        return "change"
    return _KIND_FOR_EVENT.get(kind)


def title_for(kind: TimelineKind, payload: dict[str, Any]) -> str:
    if kind == "goal":
        return str(payload.get("task") or payload.get("goal") or "Run started")
    if kind == "plan":
        content = str(payload.get("content") or payload.get("text") or "")
        return content[:72] or "Plan step"
    if kind == "reason":
        return "Reasoning"
    if kind == "tool":
        tool = str(payload.get("tool") or payload.get("name") or "tool")
        detail = str(payload.get("command") or payload.get("path") or payload.get("pattern") or "")
        return f"{tool}" + (f" · {detail[:48]}" if detail else "")
    if kind == "change":
        path = str(payload.get("path") or "")
        return path or "File change"
    if kind == "approval":
        return str(payload.get("tool") or payload.get("summary") or "Approval required")
    if kind == "verification":
        return str(payload.get("status") or payload.get("kind") or "Verification")
    if kind == "checkpoint":
        return str(payload.get("label") or payload.get("id") or "Checkpoint")
    if kind == "handoff":
        return str(payload.get("path") or "Handoff")
    if kind == "result":
        return str(payload.get("exit_status") or "Run finished")
    if kind == "error":
        return str(payload.get("message") or "Error")
    return kind


def status_for_event(kind: str, payload: dict[str, Any]) -> TimelineStatus:
    if kind in {"tool_start", "stream_reasoning", "agent_start", "verification_plan"}:
        return "running"
    if kind == "approval":
        decision = str(payload.get("decision") or "")
        if decision in {"deny", "stop"}:
            return "failed"
        if decision:
            return "ok"
        return "blocked"
    if kind in {"tool_end", "verification_record", "verification_status"}:
        if payload.get("ok") is False or payload.get("status") in {"failed", "changed_unverified"}:
            return "failed"
        return "ok"
    if kind == "submit_blocked":
        return "blocked"
    if kind == "error":
        return "failed"
    if kind == "agent_end":
        exit_status = str(payload.get("exit_status") or "").lower()
        if exit_status in {"error", "limits exceeded", "limitsexceeded", "cancelled"}:
            return "failed"
        return "ok"
    return "pending"


def affected_files(payload: dict[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    for key in ("path", "paths", "affected_paths"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
        elif isinstance(val, (list, tuple)):
            paths.extend(str(p) for p in val if p)
    diff = payload.get("diff")
    if isinstance(diff, str) and diff.startswith("---"):
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                paths.append(line[6:].strip())
    return tuple(dict.fromkeys(paths))


def make_timeline_entry(
    *,
    entry_id: str,
    kind: str,
    payload: dict[str, Any],
    sequence: int,
    timestamp: str = "",
    duration_ms: int | None = None,
) -> TimelineEntry | None:
    tl_kind = timeline_kind_for_event(kind, payload)
    if tl_kind is None:
        return None
    return TimelineEntry(
        id=entry_id,
        kind=tl_kind,
        status=status_for_event(kind, payload),
        title=title_for(tl_kind, payload),
        detail=str(payload.get("output_summary") or payload.get("summary") or payload.get("output") or "")[:200],
        timestamp=timestamp,
        duration_ms=duration_ms,
        affected_files=affected_files(payload),
        tool=str(payload.get("tool") or ""),
        sequence=sequence,
    )
