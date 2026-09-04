"""Model gateway and budget tests."""

from __future__ import annotations

import pytest

from kite.application.model import (
    BudgetLedger,
    ModelGateway,
    ProviderErrorCategory,
    RetryPolicy,
    classify_provider_error,
    is_retryable,
)


class _OkBackend:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, messages, **kwargs):
        self.calls += 1
        return {"role": "assistant", "content": "ok", "extra": {"cost": 0.01}}


class _FlakyBackend:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, messages, **kwargs):
        self.calls += 1
        if self.calls < 2:
            raise TimeoutError("connection timeout")
        return {"role": "assistant", "content": "recovered"}


class _PermanentBackend:
    def query(self, messages, **kwargs):
        raise ValueError("invalid api key format")


def test_model_gateway_complete() -> None:
    gw = ModelGateway(_OkBackend())
    resp = gw.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert resp.cost == 0.01


def test_model_gateway_retries_transient(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    gw = ModelGateway(_FlakyBackend(), retry=RetryPolicy(max_attempts=3, base_delay=0))
    resp = gw.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "recovered"


def test_permanent_error_not_retried(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    gw = ModelGateway(_PermanentBackend(), retry=RetryPolicy(max_attempts=3))
    with pytest.raises(ValueError):
        gw.complete([{"role": "user", "content": "hi"}])


def test_classify_provider_errors() -> None:
    assert classify_provider_error(TimeoutError("timed out")) == ProviderErrorCategory.RETRYABLE_TRANSIENT
    assert not is_retryable(ProviderErrorCategory.PERMANENT)


def test_budget_ledger_reserve_and_record() -> None:
    ledger = BudgetLedger(cost_limit=1.0, step_limit=5)
    assert ledger.reserve(0.5, "model")
    ledger.record({"cost": 0.3})
    assert ledger.within_limits()
    ledger.record({"cost": 0.8, "subagent": True})
    assert ledger.subagent_cost == 0.8
    assert ledger.total_cost() == 1.1
    assert not ledger.within_limits()
