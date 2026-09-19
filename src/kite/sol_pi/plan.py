"""Plan-step tracking for Online Context Compact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

PlanStatus = Literal["pending", "in_progress", "completed"]
PLAN_STATUSES = ("pending", "in_progress", "completed")
MAX_PLAN_STEPS = 128


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    goal: str
    status: PlanStatus


@dataclass(frozen=True, slots=True)
class PlanTransition:
    completed_steps: tuple[PlanStep, ...]
    advice: tuple[str, ...]


def parse_plan_steps(value: Any) -> tuple[PlanStep, ...] | None:
    if not isinstance(value, list) or len(value) > MAX_PLAN_STEPS:
        return None
    steps: list[PlanStep] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        step_id = item.get("id")
        goal = item.get("goal")
        status = item.get("status")
        if not isinstance(step_id, str) or not step_id or not isinstance(goal, str) or not goal:
            return None
        if status not in PLAN_STATUSES:
            return None
        steps.append(PlanStep(id=step_id, goal=goal, status=status))
    if len({s.id for s in steps}) != len(steps):
        return None
    return tuple(steps)


def parse_todo_items(value: Any) -> tuple[PlanStep, ...] | None:
    """Map Kite todo_write items to plan steps (content → goal)."""
    if not isinstance(value, list):
        return None
    steps: list[PlanStep] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        content = item.get("content")
        status = item.get("status")
        if not isinstance(content, str) or not content:
            return None
        if status not in PLAN_STATUSES:
            return None
        step_id = str(item.get("id") or content)
        steps.append(PlanStep(id=step_id, goal=content, status=status))
    return tuple(steps) if steps else None


def analyze_plan_transition(previous: tuple[PlanStep, ...], next_steps: tuple[PlanStep, ...]) -> PlanTransition:
    previous_by_id = {s.id: s for s in previous}
    completed: list[PlanStep] = []
    advice: list[str] = []
    for step in next_steps:
        prior = previous_by_id.get(step.id)
        if (prior is None or prior.status != "completed") and step.status == "completed":
            completed.append(step)
        if prior and prior.goal != step.goal:
            advice.append(f"Plan step {step.id!r} changed goal; reuse an id only for the same goal.")
    in_progress = sum(1 for s in next_steps if s.status == "in_progress")
    if in_progress > 1:
        advice.append("Keep at most one plan step in_progress.")
    if in_progress == 0 and any(s.status == "pending" for s in next_steps):
        advice.append("Mark one pending plan step in_progress before starting it.")
    return PlanTransition(completed_steps=tuple(completed), advice=tuple(advice))
