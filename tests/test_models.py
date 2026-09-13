from __future__ import annotations

from types import SimpleNamespace

import pytest

from kite.models.litellm_model import LitellmModel
from kite.models.reasoning import ReasoningSupport, looks_like_temperature_reasoning_error

_REASONING_ERROR = (
    "gpt-5.6-luna doesn't support temperature=0.0 while reasoning is active. "
    "Only temperature=1 is supported unless reasoning_effort resolves to 'none'."
)


def _model(*, temperature: float | None = None, mode: str = "fast") -> LitellmModel:
    model = object.__new__(LitellmModel)
    model.resolved = SimpleNamespace(litellm_kwargs=lambda: {"model": "chatgpt/gpt-5.6-luna"})
    model.registry = None
    model.temperature = temperature
    model.max_retries = 0
    model.stream = True
    model.reasoning_mode = mode
    model.reasoning_effort = "low" if mode == "fast" else ""
    model.reasoning_support = ReasoningSupport(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high"},
        fast_kwargs={"reasoning_effort": "low"},
        off_kwargs={"reasoning_effort": "none"},
    )
    model._drop_reasoning = False
    model.prompt_cache = None
    model.timeout_seconds = 0
    return model


def test_reasoning_request_omits_default_temperature() -> None:
    request = _model()._completion_kwargs([], stream=True)

    assert "temperature" not in request
    assert request["reasoning_effort"] == "low"


def test_explicit_temperature_is_preserved_without_reasoning() -> None:
    model = _model(temperature=0.0, mode="off")
    model.reasoning_support = ReasoningSupport(False, False, False, False)

    request = model._completion_kwargs([], stream=True)

    assert request["temperature"] == 0.0


def test_temperature_reasoning_error_is_detected() -> None:
    assert looks_like_temperature_reasoning_error(RuntimeError(_REASONING_ERROR))
    assert not looks_like_temperature_reasoning_error(RuntimeError("provider unavailable"))


def test_temperature_fallback_preserves_reasoning_and_removes_temperature() -> None:
    model = _model(temperature=0.0)
    attempts: list[tuple[str, float | None, bool]] = []

    def query(_messages: list[dict]) -> dict:
        attempts.append((model.reasoning_mode, model.temperature, model._drop_reasoning))
        if len(attempts) == 1:
            raise RuntimeError(_REASONING_ERROR)
        return {"ok": True}

    model._query_stream = query  # type: ignore[method-assign]

    assert model._query_stream_with_fallback([]) == {"ok": True}
    assert attempts == [("fast", 0.0, False), ("fast", None, False)]


def test_compaction_request_omits_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.agent import summarize

    captured: dict = {}

    class FakeLiteLLM:
        suppress_debug_info = False

        @staticmethod
        def completion(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="summary"))])

    monkeypatch.setitem(__import__("sys").modules, "litellm", FakeLiteLLM)
    resolved = SimpleNamespace(litellm_kwargs=lambda: {"model": "openrouter/test"})

    assert summarize._try_complete(resolved, "transcript") == "summary"
    assert "temperature" not in captured
