"""Codex/Pi-style continuity briefs for compact + budget continue."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from kite.context.window import COMPACTION_PREFIX

if TYPE_CHECKING:
    from kite.memory.store import MemoryStore

_STOP_EXITS = frozenset(
    {"Submitted", "Interrupted", "Stalled", "ProviderFault", "Error", "RepeatedFormatError"}
)


@dataclass
class ContinuityBrief:
    mission: str = ""
    done: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        def bullets(rows: list[str]) -> str:
            return "\n".join(f"- {r}" for r in rows) if rows else "- (none)"

        return (
            "## Continuity\n"
            f"- Mission: {self.mission or '(unknown)'}\n"
            f"- Done:\n{bullets(self.done)}\n"
            f"- Next:\n{bullets(self.next_steps)}\n"
            f"- Constraints:\n{bullets(self.constraints)}\n"
            f"- Paths:\n{bullets(self.paths)}\n"
            f"- Open todos:\n{bullets(self.todos)}\n"
        )


def _mission_from_messages(messages: list[dict], task: str) -> str:
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text") or p.get("content") or "") for p in content if isinstance(p, dict)
            )
        text = str(content).strip()
        if text and not text.startswith(COMPACTION_PREFIX):
            return text[:500]
    return (task or "")[:500]


def build_continuity_brief(
    *,
    messages: list[dict],
    todos: list[dict] | None = None,
    task: str = "",
) -> ContinuityBrief:
    open_todos = [
        str(t.get("content") or "").strip()
        for t in (todos or [])
        if str(t.get("status") or "") in {"pending", "in_progress"}
        and str(t.get("content") or "").strip()
    ]
    done: list[str] = []
    for m in messages[-20:]:
        if m.get("role") == "assistant":
            text = str(m.get("content") or "").strip()
            if text and not m.get("tool_calls"):
                done.append(text[:160])
                if len(done) >= 3:
                    break
    next_steps = list(open_todos[:5]) or ["Continue the unfinished task from continuity context."]
    return ContinuityBrief(
        mission=_mission_from_messages(messages, task),
        done=done or ["(see transcript)"],
        next_steps=next_steps,
        todos=open_todos,
    )


def has_unfinished_work(
    *,
    todos: list[dict] | None,
    exit_status: str,
    tool_call_count: int = 0,
) -> bool:
    status = (exit_status or "").strip()
    if status in {"Submitted", "Interrupted", "Stalled"}:
        return False
    for t in todos or []:
        if str(t.get("status") or "") in {"pending", "in_progress"}:
            return True
    return tool_call_count > 0 and status == "LimitsExceeded"


def should_budget_auto_continue(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int,
    todos: list[dict] | None,
    tool_call_count: int,
    inbox_queued: bool,
) -> bool:
    if inbox_queued:
        return False
    if continues_used >= max_continues:
        return False
    status = (exit_status or "").strip()
    if status != "LimitsExceeded":
        return False
    if status in _STOP_EXITS:
        return False
    return has_unfinished_work(todos=todos, exit_status=status, tool_call_count=tool_call_count)


def next_budget_action(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int,
    todos: list[dict] | None,
    tool_call_count: int,
    inbox_queued: bool,
) -> str:
    """Return 'continue' or 'stop' for the REPL budget chain."""
    if should_budget_auto_continue(
        exit_status=exit_status,
        continues_used=continues_used,
        max_continues=max_continues,
        todos=todos,
        tool_call_count=tool_call_count,
        inbox_queued=inbox_queued,
    ):
        return "continue"
    return "stop"


def maybe_pin_project_fact(store: MemoryStore, brief: ContinuityBrief) -> bool:
    if not (brief.paths or brief.constraints):
        return False
    notes = store.notes(scope="project")
    if len(notes) >= 40:
        return False
    bits = list(brief.paths[:3]) + list(brief.constraints[:2])
    fact = "Continuity: " + "; ".join(bits)
    fact = fact[:240]
    existing = {n.text.lower() for n in notes}
    if fact.lower() in existing:
        return False
    store.remember(fact, scope="project")
    return True


def save_continuity(
    *,
    store: MemoryStore,
    brief: ContinuityBrief,
    session_id: str,
    cwd: str,
) -> None:
    md = brief.to_markdown()
    store.record_episode(
        kind="continuity",
        summary=(brief.mission or "continuity")[:200],
        session_id=session_id,
        payload={"markdown": md, "todos": brief.todos, "paths": brief.paths},
        scope="project",
    )
    maybe_pin_project_fact(store, brief)


def latest_continuity_markdown(
    store: MemoryStore,
    *,
    session_id: str = "",
    max_chars: int = 2_000,
) -> str:
    rows = store.episodes(limit=30, scope="project")
    for ep in rows:
        if ep.kind != "continuity":
            continue
        if session_id and ep.session_id and ep.session_id != session_id:
            continue
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(ep.payload or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        md = str(payload.get("markdown") or ep.summary or "")
        if md:
            return md[:max_chars]
    return ""


def record_continuity_after_compact(
    *,
    store: MemoryStore,
    messages: list[dict],
    todos: list[dict] | None,
    session_id: str,
    cwd: str,
    task: str = "",
) -> str:
    brief = build_continuity_brief(messages=messages, todos=todos, task=task)
    save_continuity(store=store, brief=brief, session_id=session_id, cwd=cwd)
    return brief.to_markdown()
