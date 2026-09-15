from __future__ import annotations

from types import SimpleNamespace

import pytest

from kite.models.litellm_model import LitellmModel
from kite.models.reasoning import ReasoningSupport, looks_like_reasoning_error, looks_like_temperature_reasoning_error
from kite.models.usage import UsageTotals

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
    attempts: list[tuple[str, float | None, bool, dict | None]] = []

    def query(_messages: list[dict], *, overrides=None) -> dict:
        attempts.append((model.reasoning_mode, model.temperature, model._drop_reasoning, overrides))
        if len(attempts) == 1:
            raise RuntimeError(_REASONING_ERROR)
        return {"ok": True}

    model._query_stream = query  # type: ignore[method-assign]

    assert model._query_stream_with_fallback([]) == {"ok": True}
    assert attempts[0] == ("fast", 0.0, False, None)
    assert attempts[1][:3] == ("fast", 0.0, False)
    assert attempts[1][3] == {"temperature": None}
    assert model.temperature == 0.0


def test_reasoning_fallback_preserves_session_config() -> None:
    model = _model(mode="fast")
    attempts: list[tuple[str, float | None, bool]] = []
    err = RuntimeError("unsupported reasoning_effort for this model")
    assert looks_like_reasoning_error(err)

    def query(_messages: list[dict], *, overrides=None) -> dict:
        attempts.append((model.reasoning_mode, model.temperature, model._drop_reasoning))
        if len(attempts) == 1:
            raise err
        return {"ok": True}

    model._query_stream = query  # type: ignore[method-assign]

    assert model._query_stream_with_fallback([]) == {"ok": True}
    assert attempts == [("fast", None, False), ("fast", None, False)]
    assert model.reasoning_mode == "fast"
    assert model._drop_reasoning is False


def test_api_messages_drop_unanswered_tool_calls() -> None:
    model = object.__new__(LitellmModel)
    projected = model._api_messages(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "answered", "type": "function", "function": {"name": "read", "arguments": "{}"}},
                    {"id": "dangling", "type": "function", "function": {"name": "submit", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "answered", "content": "ok"},
            {"role": "user", "content": "next"},
        ]
    )

    assistant = next(m for m in projected if m["role"] == "assistant")
    assert [tc["id"] for tc in assistant["tool_calls"]] == ["answered"]
    assert [m["role"] for m in projected] == ["user", "assistant", "tool", "user"]

    emptied = model._api_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "dangling", "type": "function", "function": {"name": "submit", "arguments": "{}"}}
                ],
            }
        ]
    )
    assert emptied == []


def test_litellm_usage_serializer_warning_is_contained() -> None:
    import warnings

    from litellm.types.llms.openai import ResponsesAPIResponse

    from kite.models.litellm_model import _quiet_litellm_usage_serialization

    # Same shape LiteLLM builds: a chat-style usage dict on a ResponseAPIUsage field.
    response = ResponsesAPIResponse.model_construct(
        id="resp_test",
        created_at=0,
        output=[],
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    )
    assert isinstance(response.usage, dict)

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with _quiet_litellm_usage_serialization():
            response.model_dump()

    assert not [w for w in seen if "Pydantic serializer" in str(w.message)]


def test_usage_totals_sum_cost_across_turns() -> None:
    totals = UsageTotals()
    totals.absorb({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.02})
    totals.absorb({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.03})
    assert totals.input_tokens == 20 and totals.output_tokens == 10
    assert totals.cost == pytest.approx(0.05)


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
