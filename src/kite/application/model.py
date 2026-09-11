"""Model gateway and budget ledger."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ProviderErrorCategory(StrEnum):
    RETRYABLE_TRANSIENT = "retryable_transient"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_FAILURE = "authorization_failure"
    INVALID_REQUEST = "invalid_request"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONTEXT_OVERFLOW = "context_overflow"
    PROVIDER_CONFIGURATION_ERROR = "provider_configuration_error"
    PERMANENT = "permanent"


def classify_provider_error(exc: BaseException) -> ProviderErrorCategory:
    name = exc.__class__.__name__
    msg = str(exc).lower()
    if name in ("AuthenticationError", "AuthenticationException"):
        return ProviderErrorCategory.AUTHENTICATION_FAILURE
    if name in ("PermissionDeniedError", "AuthorizationException"):
        return ProviderErrorCategory.AUTHORIZATION_FAILURE
    if "rate limit" in msg or "429" in msg:
        return ProviderErrorCategory.RATE_LIMITED
    if "context" in msg and ("length" in msg or "overflow" in msg or "too long" in msg):
        return ProviderErrorCategory.CONTEXT_OVERFLOW
    if name in ("BadRequestError", "InvalidRequestError"):
        return ProviderErrorCategory.INVALID_REQUEST
    from kite.models.retry import is_transient_provider_error

    if is_transient_provider_error(exc):
        return ProviderErrorCategory.RETRYABLE_TRANSIENT
    return ProviderErrorCategory.PERMANENT


def is_retryable(category: ProviderErrorCategory) -> bool:
    return category in (
        ProviderErrorCategory.RETRYABLE_TRANSIENT,
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.MODEL_UNAVAILABLE,
    )


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
        return self.recorded_cost

    def within_limits(self) -> bool:
        if self.cost_limit is not None and self.total_cost() > self.cost_limit:
            return False
        if self.step_limit is not None and self.recorded_steps > self.step_limit:
            return False
        return True


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class ModelBackend(Protocol):
    def query(self, messages: list[dict], **kwargs: Any) -> dict: ...


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 2.0
    cap_delay: float = 30.0
    jitter: float = 0.25

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return retry_after
        delay = min(self.cap_delay, self.base_delay * (2 ** (attempt - 1)))
        return delay * (1 + random.uniform(-self.jitter, self.jitter))


class ModelGateway:
    """Adapter-driven model access with typed retries."""

    def __init__(
        self,
        backend: ModelBackend,
        *,
        retry: RetryPolicy | None = None,
        on_usage: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.backend = backend
        self.retry = retry or RetryPolicy()
        self.on_usage = on_usage

    def complete(
        self,
        messages: list[dict],
        *,
        context: Any = None,
        budget: Any = None,
        **kwargs: Any,
    ) -> ModelResponse:
        last_exc: BaseException | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                raw = self.backend.query(messages, **kwargs)
                extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
                usage = dict(raw.get("usage") or extra.get("usage") or {})
                cost = float(raw.get("cost") or extra.get("cost") or usage.get("cost") or 0)
                if self.on_usage:
                    self.on_usage({"usage": usage, "cost": cost})
                return ModelResponse(
                    content=str(raw.get("content") or ""),
                    tool_calls=list(raw.get("tool_calls") or []),
                    usage=usage,
                    cost=cost,
                    raw=raw,
                )
            except BaseException as exc:
                last_exc = exc
                if not is_retryable(classify_provider_error(exc)) or attempt >= self.retry.max_attempts:
                    raise
                time.sleep(self.retry.delay_for(attempt))
        raise last_exc or RuntimeError("model query failed")

    def stream(self, messages: list[dict], **kwargs: Any) -> Iterator[str]:
        resp = self.complete(messages, **kwargs)
        text = resp.content
        if not text:
            return iter(())
        chunk = max(1, len(text) // 4)
        return (text[i : i + chunk] for i in range(0, len(text), chunk))
