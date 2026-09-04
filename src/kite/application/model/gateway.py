"""Model gateway contracts and LiteLLM adapter."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

from kite.application.model.errors import ProviderErrorCategory, classify_provider_error, is_retryable


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    streaming: bool = True
    vision: bool = False
    reasoning: bool = False


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

    def capabilities(self, model: str = "") -> ModelCapabilities:
        return ModelCapabilities(streaming=True, vision=False, reasoning=False)

    def complete(self, messages: list[dict], *, context: Any = None, budget: Any = None, **kwargs: Any) -> ModelResponse:
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
                category = classify_provider_error(exc)
                if not is_retryable(category) or attempt >= self.retry.max_attempts:
                    raise
                time.sleep(self.retry.delay_for(attempt))
        raise last_exc or RuntimeError("model query failed")

    def stream(self, messages: list[dict], **kwargs: Any) -> Iterator[str]:
        """Fallback stream — single blocking completion chunked."""
        resp = self.complete(messages, **kwargs)
        text = resp.content
        if not text:
            return iter(())
        chunk = max(1, len(text) // 4)
        return (text[i : i + chunk] for i in range(0, len(text), chunk))
