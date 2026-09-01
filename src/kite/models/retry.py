"""Classify provider/network faults and compute retry backoff."""

from __future__ import annotations

_TRANSIENT_HINTS = (
    "timeout",
    "timed out",
    "connection",
    "connect",
    "network",
    "unreachable",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "too many requests",
    "429",
    "502",
    "503",
    "504",
    "529",
    "overloaded",
    "service unavailable",
    "temporarily unavailable",
    "internal server error",
    "ssl",
    "eof",
    "reset by peer",
    "broken pipe",
    "name or service not known",
    "failed to establish",
    "connection refused",
    "connection reset",
    "api connection",
    "openai.error",
    "anthropic",
    "litellm",
)

_TRANSIENT_TYPES = frozenset(
    {
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "APIConnectionError",
        "ServiceUnavailableError",
        "RateLimitError",
        "InternalServerError",
        "APIError",
    }
)


def is_transient_provider_error(exc: BaseException) -> bool:
    """True when a provider call may succeed on retry (network blip, 429, 5xx)."""
    name = exc.__class__.__name__
    if name in _TRANSIENT_TYPES:
        return True
    msg = str(exc).lower()
    return any(hint in msg for hint in _TRANSIENT_HINTS)


def retry_delay_s(attempt: int, *, base: float = 2.0, cap: float = 30.0) -> float:
    """Exponential backoff for attempt 1, 2, 3…"""
    if attempt < 1:
        attempt = 1
    return min(cap, base * (2 ** (attempt - 1)))
