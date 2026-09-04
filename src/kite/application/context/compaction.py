"""Structured compaction state preservation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompactionState:
    """Fields that must survive compaction."""

    constraints: list[str] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    changed_hashes: dict[str, str] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cwd: str = ""
    execution_mode: str = "restricted"
    provider: str = ""
    model: str = ""
    budget_state: dict[str, Any] = field(default_factory=dict)
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraints": self.constraints,
            "todos": self.todos,
            "changed_paths": self.changed_paths,
            "changed_hashes": self.changed_hashes,
            "checks": self.checks,
            "errors": self.errors,
            "cwd": self.cwd,
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "model": self.model,
            "budget_state": self.budget_state,
            "pending_tool_calls": self.pending_tool_calls,
            "checkpoint_ids": self.checkpoint_ids,
        }


def extract_compaction_state(
    messages: list[dict],
    *,
    cwd: str = "",
    todos: list[dict] | None = None,
    session_meta: dict | None = None,
) -> CompactionState:
    """Extract structured state from messages before compaction."""
    from kite.context.window import extract_compaction_facts

    state = CompactionState(cwd=cwd, todos=list(todos or []))
    facts = extract_compaction_facts(messages)
    state.constraints = [f for f in facts if f.startswith("constraint:")]
    meta = session_meta or {}
    state.provider = str(meta.get("provider") or "")
    state.model = str(meta.get("model") or "")
    state.execution_mode = str(meta.get("execution_mode") or "restricted")

    pending: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                pending.append(tc)
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            pending = [p for p in pending if p.get("id") != tc_id]
    state.pending_tool_calls = pending
    return state


def pair_tool_messages(messages: list[dict]) -> list[dict]:
    """Ensure assistant tool calls stay paired with tool results."""
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        out.append(msg)
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            ids = {tc.get("id") for tc in msg["tool_calls"]}
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                if messages[j].get("tool_call_id") in ids:
                    out.append(messages[j])
                j += 1
            i = j
            continue
        i += 1
    return out
