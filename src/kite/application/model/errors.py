"""Typed provider error categories."""

from __future__ import annotations

from enum import Enum


class ProviderErrorCategory(str, Enum):
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
