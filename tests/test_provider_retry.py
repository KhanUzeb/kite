"""Provider retry classification and agent fault handling."""

from __future__ import annotations

import pytest

from kite.agent.exceptions import ProviderFault
from kite.models.retry import is_transient_provider_error, retry_delay_s


def test_transient_timeout_and_rate_limit() -> None:
    assert is_transient_provider_error(TimeoutError("connection timed out"))
    assert is_transient_provider_error(RuntimeError("Rate limit exceeded (429)"))
    assert is_transient_provider_error(Exception("503 Service Unavailable"))


def test_non_transient_auth_error() -> None:
    assert not is_transient_provider_error(ValueError("invalid api key"))
    assert not is_transient_provider_error(RuntimeError("model not found"))


def test_retry_delay_exponential() -> None:
    assert retry_delay_s(1) == 2.0
    assert retry_delay_s(2) == 4.0
    assert retry_delay_s(5) == 30.0


def test_provider_fault_carries_attempts() -> None:
    fault = ProviderFault("network down", attempts=4)
    assert fault.error == "network down"
    assert fault.attempts == 4
