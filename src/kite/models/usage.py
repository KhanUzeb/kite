"""Session usage totals for cache/cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0

    def absorb(self, raw: dict[str, Any] | None) -> None:
        if not raw:
            return
        self.input_tokens += int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
        self.output_tokens += int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
        self.cache_read_tokens += int(raw.get("cache_read_tokens") or raw.get("cache_read") or raw.get("cached") or 0)
        self.cache_write_tokens += int(
            raw.get("cache_creation_tokens") or raw.get("cache_write") or raw.get("cache_creation") or 0
        )
        try:
            delta = float(raw.get("cost") or 0.0)
        except (TypeError, ValueError):
            delta = 0.0
        if delta:
            self.cost = max(self.cost, delta)

    def absorb_session(self, session: dict[str, Any] | None) -> None:
        if not session:
            return
        self.input_tokens = int(session.get("prompt_tokens") or self.input_tokens)
        self.output_tokens = int(session.get("completion_tokens") or self.output_tokens)
        self.cache_read_tokens = int(
            session.get("cache_read_tokens") or session.get("cache_hit_tokens") or self.cache_read_tokens
        )
        self.cache_write_tokens = int(session.get("cache_creation_tokens") or self.cache_write_tokens)

    @property
    def cache_hit_ratio(self) -> float:
        prompt = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        if prompt <= 0:
            return 0.0
        return self.cache_read_tokens / prompt
