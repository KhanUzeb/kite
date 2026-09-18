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
            self.cost += delta

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

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


def provider_quota(provider: str | None) -> dict[str, Any] | None:
    """Optional provider quota/rate-limit snapshot.

    No provider currently exposes a quota API to the harness, so this
    returns ``None`` by default. Providers may later plug in a real
    implementation behind this hook; callers must treat ``None`` as
    "not available" and still render local session totals.
    """
    _ = (provider or "").strip()
    return None


def format_usage_report(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    api_calls: int = 0,
    cost: float = 0.0,
    context_tokens: int = 0,
    context_window: int = 0,
    provider: str = "",
    quota: dict[str, Any] | None = None,
    quota_available: bool | None = None,
) -> dict[str, Any]:
    """Build a ``/usage`` report as data + pre-formatted text lines.

    Pure helper — rendering lives in the REPL handler so this stays
    testable without a console. ``quota=None`` means the provider did
    not report limits; the local totals still render.
    """
    total = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    lines = ["Usage", ""]
    lines.append("Session")
    lines.append(f"  Input tokens:       {input_tokens:,}")
    lines.append(f"  Output tokens:      {output_tokens:,}")
    lines.append(f"  Cache read tokens:  {cache_read_tokens:,}")
    lines.append(f"  Cache write tokens: {cache_write_tokens:,}")
    lines.append(f"  Total tokens:       {total:,}")
    lines.append(f"  API calls:          {api_calls:,}")
    lines.append(f"  Cost:               ${cost:.4f}")
    lines.append("")
    lines.append("Context")
    if context_window > 0:
        pct = (context_tokens / context_window * 100.0) if context_window else 0.0
        lines.append(f"  Estimated tokens: {context_tokens:,} / {context_window:,}")
        lines.append(f"  Context usage:    {pct:.1f}%")
    else:
        lines.append(f"  Estimated tokens: {context_tokens:,}")
        lines.append("  Context usage:    —")
    lines.append("")
    lines.append("Providers")
    name = (provider or "").strip() or "—"
    lines.append(f"  {name}")
    resolved_quota = quota if quota is not None else provider_quota(provider or None)
    if resolved_quota:
        for key in ("rate_limit", "usage", "resets", "reset", "account", "window"):
            value = resolved_quota.get(key)
            if value is not None and str(value).strip():
                lines.append(f"    {key.replace('_', ' ').title()}: {value}")
        if len(lines) <= 12:
            lines.append(f"    Detail: {resolved_quota}")
    elif quota_available is False:
        lines.append("    Rate limit: unavailable for this provider")
        lines.append("    Resets:     unavailable for this provider")
    else:
        lines.append("    Rate limit: available if supported")
        lines.append("    Resets:     available if supported")
    return {"total_tokens": total, "cost": cost, "text": "\n".join(lines)}
