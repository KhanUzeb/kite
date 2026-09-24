"""Per-task token/cost baseline (§1 of the token-efficiency guide).

Renders real requests into cost share by source × billing type so removals can
be ranked by ``share of spend × fraction removable ÷ quality risk``.

Sources: system prompt, tool definitions, skill/rule setup, user messages,
file reads, search results, command/tool output, history, summaries, subagents.
Billing types follow the provider: output, uncached input, cached input —
priced very differently, so raw token counts alone mislead.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RequestBreakdown:
    system_tokens: int = 0
    tool_tokens: int = 0
    setup_tokens: int = 0  # skills / rules / environment / summaries pinned after the breakpoint
    history_tokens: int = 0  # conversation turns (user + assistant + tool results)
    total_tokens: int = 0
    message_count: int = 0
    static_tokens: int = 0  # system + tools: resent on every turn

    @property
    def shares(self) -> dict[str, float]:
        total = max(1, self.total_tokens)
        return {
            "system": self.system_tokens / total,
            "tools": self.tool_tokens / total,
            "setup": self.setup_tokens / total,
            "history": self.history_tokens / total,
        }


@dataclass
class RunBaseline:
    breakdown: RequestBreakdown = field(default_factory=RequestBreakdown)
    turns_per_task: float = 0.0
    cache_hit_rate: float = 0.0
    per_tool_use_rate: dict[str, float] = field(default_factory=dict)
    per_tool_error_rate: dict[str, float] = field(default_factory=dict)


def _is_summary_message(m: dict) -> bool:
    content = m.get("content") or ""
    text = content if isinstance(content, str) else ""
    extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
    return bool(extra.get("compacted")) or text.startswith("Previous conversation summary:")


def breakdown_request(
    *,
    system: str = "",
    tool_schemas: list[dict] | None = None,
    messages: list[dict] | None = None,
) -> RequestBreakdown:
    """Count tokens per section with the harness tokenizer estimate."""
    from kite.context.window import estimate_message_tokens, estimate_text_tokens, estimate_tool_schema_tokens

    messages = messages or []
    system_tokens = estimate_text_tokens(system)
    tool_tokens = estimate_tool_schema_tokens(tool_schemas or [])
    setup_tokens = 0
    history_tokens = 0
    count = 0
    for m in messages:
        if m.get("role") == "exit":
            continue
        count += 1
        tokens = estimate_message_tokens(m)
        if m.get("role") == "system":
            continue  # already counted via `system` to avoid double-counting
        if _is_summary_message(m):
            setup_tokens += tokens
        else:
            history_tokens += tokens
    total = system_tokens + tool_tokens + setup_tokens + history_tokens
    return RequestBreakdown(
        system_tokens=system_tokens,
        tool_tokens=tool_tokens,
        setup_tokens=setup_tokens,
        history_tokens=history_tokens,
        total_tokens=total,
        message_count=count,
        static_tokens=system_tokens + tool_tokens,
    )


def price_weighted_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    model_name: str = "",
) -> float:
    """Price-weighted cost for one request using LiteLLM's own cost map.

    Falls back to ratio weighting (output 3×, cached 0.1× uncached input) when
    the model has no cost entry, so per-task comparisons stay meaningful.
    """
    try:
        from kite.models.litellm_model import estimate_cost_from_usage

        cost = estimate_cost_from_usage(model_name, prompt_tokens, completion_tokens, cache_read_tokens)
        if cost > 0:
            return cost
    except Exception:
        pass
    fresh = max(0, prompt_tokens - max(0, cache_read_tokens))
    return fresh * 1.0 + max(0, cache_read_tokens) * 0.1 + max(0, completion_tokens) * 3.0


def summarize_run(
    *,
    system: str = "",
    tool_schemas: list[dict] | None = None,
    messages: list[dict] | None = None,
    tool_counts: dict[str, int] | None = None,
    tool_errors: dict[str, int] | None = None,
    total_runs: int = 1,
    cache_hit_rate: float = 0.0,
) -> RunBaseline:
    """Baseline for §8 validation: tokens, turns, cache hits, per-tool use/error."""
    messages = messages or []
    breakdown = breakdown_request(system=system, tool_schemas=tool_schemas, messages=messages)
    turns = 0
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            turns += 1
    tool_counts = tool_counts or {}
    tool_errors = tool_errors or {}
    runs = max(1, total_runs)
    use_rate = {name: min(1.0, count / runs) for name, count in tool_counts.items()}
    error_rate: dict[str, float] = {}
    for name, errors in tool_errors.items():
        calls = max(1, tool_counts.get(name, 0))
        error_rate[name] = errors / calls
    return RunBaseline(
        breakdown=breakdown,
        turns_per_task=turns / runs,
        cache_hit_rate=cache_hit_rate,
        per_tool_use_rate=use_rate,
        per_tool_error_rate=error_rate,
    )


def format_baseline_report(baseline: RunBaseline) -> str:
    """Pre-formatted lines for logs / PR report-backs."""
    b = baseline.breakdown
    lines = [
        "Token baseline (per task, price-weighted by billing type)",
        f"  static/request: {b.static_tokens:,} tokens (system {b.system_tokens:,} + tools {b.tool_tokens:,})",
        f"  setup: {b.setup_tokens:,}  history: {b.history_tokens:,}  total: {b.total_tokens:,}",
        f"  turns/task: {baseline.turns_per_task:.1f}  cache hit rate: {baseline.cache_hit_rate:.1%}",
    ]
    if baseline.per_tool_use_rate:
        top = sorted(baseline.per_tool_use_rate.items(), key=lambda kv: -kv[1])[:8]
        lines.append("  tools: " + ", ".join(f"{k} {v:.0%}" for k, v in top))
    return "\n".join(lines)


def rank_opportunities(
    breakdown: RequestBreakdown,
    *,
    removable_fraction: dict[str, float] | None = None,
    quality_risk: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Rank sections by share × fraction removable ÷ quality risk (§1)."""
    removable_fraction = removable_fraction or {}
    quality_risk = quality_risk or {}
    ranked: list[tuple[str, float]] = []
    for source, share in breakdown.shares.items():
        frac = float(removable_fraction.get(source, 0.5))
        risk = max(0.1, float(quality_risk.get(source, 1.0)))
        ranked.append((source, share * frac / risk))
    ranked.sort(key=lambda kv: -kv[1])
    return ranked
