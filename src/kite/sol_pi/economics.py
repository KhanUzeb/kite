"""Online Context Compact economics (ported from NVlabs/SoL-Pi)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CompactionReason = Literal[
    "economic",
    "window_protection",
    "deferred_economic",
    "deferred_subsequent_margin",
    "deferred_carried_debt",
    "horizon_unavailable",
    "cache_ratio_unavailable",
    "native_not_compactable",
    "non_positive_saving",
]

MINIMUM_VARIANCE_SAMPLES = 3
SMALL_SAMPLE_SCALE = 0.5


@dataclass(frozen=True, slots=True)
class CompactionEconomics:
    remaining_request_scale: float = 1.0
    remaining_request_stddev_k: float = 0.0
    window_reserve_tokens: int = 16_384
    first_compaction_request_scale: float = 2.0
    subsequent_compaction_margin: float = 1.5


DEFAULT_COMPACTION_ECONOMICS = CompactionEconomics()


@dataclass(frozen=True, slots=True)
class RequestHorizonEstimate:
    completed_boundary_request_counts: tuple[int, ...]
    requests_per_boundary_mean: float
    requests_per_boundary_lower_bound: float
    unbounded_expected_remaining_requests: int
    average_context_token_increment: float | None
    window_request_upper_bound: int | None
    expected_remaining_requests: int


@dataclass(frozen=True, slots=True)
class CompactionDecision:
    write_tokens: int
    archive_tokens: int
    memo_tokens: int
    context_tokens: int
    completed_boundary_request_counts: tuple[int, ...] | None
    requests_per_boundary_mean: float | None
    requests_per_boundary_lower_bound: float | None
    unbounded_expected_remaining_requests: int | None
    average_context_token_increment: float | None
    window_request_upper_bound: int | None
    expected_remaining_requests: int | None
    breakeven_requests: float | None
    combined_breakeven_requests: float | None
    effective_horizon_requests: float | None
    cache_write_read_ratio: float | None
    incremental_cache_cost_ratio: float | None
    prior_compaction_count: int
    carried_debt_tokens: int
    cache_debt_repayment_tokens: int
    compact: bool
    reason: CompactionReason


def estimate_remaining_requests(
    *,
    completed_boundary_request_counts: tuple[int, ...],
    remaining_boundaries: int,
    scale: float,
    standard_deviation_k: float,
    context_tokens: int,
    context_window_tokens: int | None,
    average_context_token_increment: float | None,
) -> RequestHorizonEstimate:
    counts = completed_boundary_request_counts
    mean = sum(counts) / max(1, len(counts))
    lower_bound = mean
    if standard_deviation_k != 0:
        if len(counts) < MINIMUM_VARIANCE_SAMPLES:
            lower_bound = mean * SMALL_SAMPLE_SCALE
        else:
            variance = sum((c - mean) ** 2 for c in counts) / (len(counts) - 1)
            deviation = variance ** 0.5
            lower_bound = max(0.0, mean - standard_deviation_k * deviation)

    unbounded = 1 + int(lower_bound * max(0, remaining_boundaries) * scale)
    window_upper: int | None = None
    if (
        context_window_tokens is not None
        and average_context_token_increment is not None
        and average_context_token_increment > 0
    ):
        window_upper = max(
            0,
            int((context_window_tokens - context_tokens) / average_context_token_increment),
        )

    expected = unbounded if window_upper is None else min(unbounded, window_upper)
    return RequestHorizonEstimate(
        completed_boundary_request_counts=tuple(counts),
        requests_per_boundary_mean=mean,
        requests_per_boundary_lower_bound=lower_bound,
        unbounded_expected_remaining_requests=unbounded,
        average_context_token_increment=average_context_token_increment,
        window_request_upper_bound=window_upper,
        expected_remaining_requests=expected,
    )


def decide_compaction(
    *,
    write_tokens: int,
    archive_tokens: int,
    memo_tokens: int,
    context_tokens: int,
    completed_boundary_request_counts: tuple[int, ...] | None,
    remaining_boundaries: int,
    average_context_token_increment: float | None,
    context_window_tokens: int | None,
    prior_compaction_count: int,
    carried_debt_tokens: int,
    cache_debt_repayment_tokens: int,
    cache_write_read_ratio: float | None,
    economics: CompactionEconomics = DEFAULT_COMPACTION_ECONOMICS,
) -> CompactionDecision:
    horizon: RequestHorizonEstimate | None = None
    if completed_boundary_request_counts is not None:
        horizon = estimate_remaining_requests(
            completed_boundary_request_counts=completed_boundary_request_counts,
            remaining_boundaries=remaining_boundaries,
            scale=economics.remaining_request_scale,
            standard_deviation_k=economics.remaining_request_stddev_k,
            context_tokens=context_tokens,
            context_window_tokens=context_window_tokens,
            average_context_token_increment=average_context_token_increment,
        )

    saving_tokens = archive_tokens - memo_tokens
    incremental_ratio = None if cache_write_read_ratio is None else max(0.0, cache_write_read_ratio - 1.0)
    breakeven = (
        (write_tokens * incremental_ratio) / saving_tokens
        if saving_tokens > 0 and incremental_ratio is not None
        else None
    )
    combined_breakeven = (
        (carried_debt_tokens + write_tokens * incremental_ratio) / saving_tokens
        if saving_tokens > 0 and incremental_ratio is not None
        else None
    )

    first = prior_compaction_count == 0
    effective_horizon: float | None = None
    if horizon is not None:
        if first:
            cap = horizon.window_request_upper_bound
            scaled = horizon.expected_remaining_requests * economics.first_compaction_request_scale
            effective_horizon = min(scaled, cap if cap is not None else float("inf"))
        else:
            effective_horizon = float(horizon.expected_remaining_requests)

    window_protection = (
        context_window_tokens is not None
        and context_tokens >= context_window_tokens - economics.window_reserve_tokens
    )

    base_economic = (
        horizon is not None
        and horizon.expected_remaining_requests > 0
        and breakeven is not None
        and breakeven <= horizon.expected_remaining_requests
    )
    first_economic = (
        first
        and effective_horizon is not None
        and effective_horizon > 0
        and breakeven is not None
        and breakeven <= effective_horizon
    )
    subsequent_margin = (
        not first
        and horizon is not None
        and breakeven is not None
        and breakeven * economics.subsequent_compaction_margin <= horizon.expected_remaining_requests
    )
    carried_debt_gate = (
        not first
        and horizon is not None
        and combined_breakeven is not None
        and combined_breakeven <= horizon.expected_remaining_requests
    )
    economic = first_economic if first else base_economic and subsequent_margin and carried_debt_gate
    compressible = saving_tokens > 0
    compact = compressible and (window_protection or economic)

    if not compressible:
        reason: CompactionReason = "non_positive_saving"
    elif window_protection:
        reason = "window_protection"
    elif economic:
        reason = "economic"
    elif horizon is None:
        reason = "horizon_unavailable"
    elif breakeven is None:
        reason = "cache_ratio_unavailable"
    elif not first and base_economic and not subsequent_margin:
        reason = "deferred_subsequent_margin"
    elif not first and base_economic and not carried_debt_gate:
        reason = "deferred_carried_debt"
    else:
        reason = "deferred_economic"

    return CompactionDecision(
        write_tokens=write_tokens,
        archive_tokens=archive_tokens,
        memo_tokens=memo_tokens,
        context_tokens=context_tokens,
        completed_boundary_request_counts=horizon.completed_boundary_request_counts if horizon else None,
        requests_per_boundary_mean=horizon.requests_per_boundary_mean if horizon else None,
        requests_per_boundary_lower_bound=horizon.requests_per_boundary_lower_bound if horizon else None,
        unbounded_expected_remaining_requests=horizon.unbounded_expected_remaining_requests if horizon else None,
        average_context_token_increment=average_context_token_increment,
        window_request_upper_bound=horizon.window_request_upper_bound if horizon else None,
        expected_remaining_requests=horizon.expected_remaining_requests if horizon else None,
        breakeven_requests=breakeven,
        combined_breakeven_requests=combined_breakeven,
        effective_horizon_requests=effective_horizon,
        cache_write_read_ratio=cache_write_read_ratio,
        incremental_cache_cost_ratio=incremental_ratio,
        prior_compaction_count=prior_compaction_count,
        carried_debt_tokens=carried_debt_tokens,
        cache_debt_repayment_tokens=cache_debt_repayment_tokens,
        compact=compact,
        reason=reason,
    )
