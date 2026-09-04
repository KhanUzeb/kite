"""Shared budget and usage ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BudgetLedger:
    cost_limit: float | None = None
    step_limit: int | None = None
    reserved_cost: float = 0.0
    recorded_cost: float = 0.0
    recorded_steps: int = 0
    subagent_cost: float = 0.0
    usage_entries: list[dict[str, Any]] = field(default_factory=list)

    def reserve(self, amount: float, reason: str) -> bool:
        if self.cost_limit is None:
            self.reserved_cost += amount
            return True
        if self.recorded_cost + self.reserved_cost + amount > self.cost_limit:
            return False
        self.reserved_cost += amount
        self.usage_entries.append({"type": "reserve", "amount": amount, "reason": reason})
        return True

    def record(self, usage: dict[str, Any]) -> None:
        cost = float(usage.get("cost") or 0)
        self.reserved_cost = max(0.0, self.reserved_cost - cost)
        self.recorded_cost += cost
        if usage.get("subagent"):
            self.subagent_cost += cost
        self.recorded_steps += 1
        self.usage_entries.append({"type": "record", **usage})

    def total_cost(self) -> float:
        return self.recorded_cost + self.subagent_cost

    def within_limits(self) -> bool:
        if self.cost_limit is not None and self.total_cost() > self.cost_limit:
            return False
        if self.step_limit is not None and self.recorded_steps > self.step_limit:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_limit": self.cost_limit,
            "step_limit": self.step_limit,
            "recorded_cost": self.recorded_cost,
            "subagent_cost": self.subagent_cost,
            "recorded_steps": self.recorded_steps,
            "within_limits": self.within_limits(),
        }
