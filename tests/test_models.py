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


def test_completion_kwargs_temperature_without_reasoning() -> None:
    request = _model()._completion_kwargs([], stream=True)

    assert "temperature" not in request
    assert request["reasoning_effort"] == "low"

    plain = _model(temperature=0.0, mode="off")
    plain.reasoning_support = ReasoningSupport(False, False, False, False)

    plain_request = plain._completion_kwargs([], stream=True)

    assert plain_request["temperature"] == 0.0


def test_temperature_and_reasoning_error_fallbacks() -> None:
    assert looks_like_temperature_reasoning_error(RuntimeError(_REASONING_ERROR))
    assert not looks_like_temperature_reasoning_error(RuntimeError("provider unavailable"))

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

    fast = _model(mode="fast")
    fallback_attempts: list[tuple[str, float | None, bool]] = []
    err = RuntimeError("unsupported reasoning_effort for this model")
    assert looks_like_reasoning_error(err)

    def fallback_query(_messages: list[dict], *, overrides=None) -> dict:
        fallback_attempts.append((fast.reasoning_mode, fast.temperature, fast._drop_reasoning))
        if len(fallback_attempts) == 1:
            raise err
        return {"ok": True}

    fast._query_stream = fallback_query  # type: ignore[method-assign]

    assert fast._query_stream_with_fallback([]) == {"ok": True}
    assert fallback_attempts == [("fast", None, False), ("fast", None, False)]
    assert fast.reasoning_mode == "fast"
    assert fast._drop_reasoning is False


def test_completion_kwargs_single_attempt_agent_loop_owns_retries() -> None:
    """LiteLLM must not retry internally — the agent loop owns provider retries.

    Stacking both loops (3 LiteLLM attempts x 4 agent attempts) multiplies
    user-visible delay and prints one raw error line per attempt.
    """
    request = _model()._completion_kwargs([], stream=True)
    assert request["num_retries"] == 0
    assert _model()._completion_kwargs([], stream=False)["num_retries"] == 0


def test_stream_stall_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """A held-open stream must raise TimeoutError quickly, not hang the turn."""
    import sys
    import time

    def _hanging():
        time.sleep(20)
        yield SimpleNamespace(choices=[])

    class FakeLiteLLM:
        suppress_debug_info = False

        @staticmethod
        def completion(**_kwargs):
            return _hanging()

    monkeypatch.setitem(sys.modules, "litellm", FakeLiteLLM)
    model = _model()
    model.resolved = SimpleNamespace(
        provider="nvidia",
        model="deepseek-ai/deepseek-v4.1-flash",
        litellm_kwargs=lambda: {"model": "nvidia_nim/deepseek-ai/deepseek-v4.1-flash"},
    )
    model.timeout_seconds = 2
    model.on_event = None
    model.should_stop = lambda: False  # type: ignore[method-assign]

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="stalled|timed out"):
        model._query_stream([{"role": "user", "content": "hi"}])
    assert time.monotonic() - started < 15.0


def test_peek_reasoning_cache_only() -> None:
    from kite.models import reasoning

    key = ("peek-provider-xyz", "peek-model-xyz")
    assert reasoning.peek_reasoning(*key) is None
    support = ReasoningSupport(False, False, False, False)
    reasoning._cache[key] = support
    try:
        assert reasoning.peek_reasoning("  peek-provider-xyz ", "peek-model-xyz") is support
    finally:
        reasoning._cache.pop(key, None)


def test_api_messages_repair_unanswered_tool_calls() -> None:
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
    assert [tc["id"] for tc in assistant["tool_calls"]] == ["answered", "dangling"]
    assert [m["role"] for m in projected] == ["user", "assistant", "tool", "tool", "user"]
    assert projected[2]["content"] == "ok"
    assert "interrupted" in projected[3]["content"]

    repaired = model._api_messages(
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
    assert [m["role"] for m in repaired] == ["assistant", "tool"]
    assert repaired[1]["tool_call_id"] == "dangling"


def test_token_efficiency_reasoning_and_cache_breakpoints() -> None:
    from kite.models.cache import apply_cache_breakpoints

    model = object.__new__(LitellmModel)
    # Reasoning continuity: prior thinking passes through even from legacy extra-only transcripts.
    projected = model._api_messages(
        [
            {"role": "system", "content": "sys"},
            {
                "role": "assistant",
                "content": "working",
                "extra": {"reasoning": "plan: check auth then edit"},
            },
            {"role": "user", "content": "next"},
        ]
    )
    assistant = next(m for m in projected if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == "plan: check auth then edit"

    # Two-breakpoint layout: system + compaction summary both pin the stable prefix.
    msgs = [
        {"role": "system", "content": "stable instructions"},
        {"role": "user", "content": "Previous conversation summary:\nfoo"},
        {"role": "user", "content": "volatile follow-up"},
    ]
    out = apply_cache_breakpoints(msgs, provider="anthropic")
    assert out[0]["content"][0].get("cache_control") == {"type": "ephemeral"}
    assert out[1]["content"][0].get("cache_control") == {"type": "ephemeral"}
    assert isinstance(out[2]["content"], str)

    # Single summary without system still gets one breakpoint (backward compat).
    solo = apply_cache_breakpoints(
        [{"role": "user", "content": "Previous conversation summary:\nfoo"}],
        provider="anthropic",
    )
    assert solo[0]["content"][0].get("cache_control") == {"type": "ephemeral"}

    # Setup message after the system prefix gets the second breakpoint.
    setup_msgs = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "# Setup (reference — not the task)\n- cwd: /r", "extra": {"setup": True}},
        {"role": "user", "content": "do work"},
    ]
    setup_out = apply_cache_breakpoints(setup_msgs, provider="anthropic")
    assert setup_out[1]["content"][0].get("cache_control") == {"type": "ephemeral"}
    assert isinstance(setup_out[2]["content"], str)


def test_token_efficiency_report_and_routing() -> None:
    from kite.context.token_report import breakdown_request, price_weighted_cost, rank_opportunities, summarize_run
    from kite.models.routing import route_turn

    msgs = [
        {"role": "user", "content": "# Setup (reference — not the task)\nx"},
        {"role": "assistant", "content": "hi", "tool_calls": [{"id": "1", "function": {"name": "read"}}]},
        {"role": "user", "content": "next"},
    ]
    breakdown = breakdown_request(system="sys", tool_schemas=[{"function": {"name": "read"}}], messages=msgs)
    assert breakdown.static_tokens > 0 and breakdown.total_tokens > breakdown.static_tokens
    assert price_weighted_cost(prompt_tokens=100, completion_tokens=10, cache_read_tokens=90, model_name="unknown-xyz") > 0
    ranked = rank_opportunities(breakdown)
    assert [name for name, _ in ranked] and breakdown.shares["history"] >= 0
    run = summarize_run(system="sys", messages=msgs, tool_counts={"read": 1}, tool_errors={}, total_runs=1)
    assert run.turns_per_task == 1.0

    assert route_turn("hi", enabled=False) == "frontier"
    assert route_turn("hi?", enabled=True) == "cheap"
    assert route_turn("implement auth fix", enabled=True) == "frontier"


def test_usage_tracking_and_litellm_serializer() -> None:
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


def _menu_support() -> ReasoningSupport:
    return ReasoningSupport(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high"},
        fast_kwargs={"reasoning_effort": "low"},
        efforts=("none", "low", "medium", "high"),
    )


def test_thinking_level_clamp_and_apply(tmp_path, kite_home) -> None:
    from io import StringIO

    from rich.console import Console

    from kite.models.reasoning import clamp_thinking_level
    from kite.ui.repl import ChatSession
    from tests.conftest import strip_ansi

    info = _menu_support()
    # Exact hits pass through.
    assert clamp_thinking_level("high", info) == ("thinking:high", "high")
    assert clamp_thinking_level("off", info) == ("off", "off")
    # Unsupported xhigh/max clamp down to high (nearest; ties prefer cheaper).
    assert clamp_thinking_level("xhigh", info) == ("thinking:high", "high")
    assert clamp_thinking_level("max", info) == ("thinking:high", "high")
    # Unknown tokens and level-less models give nothing.
    assert clamp_thinking_level("turbo", info) is None
    assert clamp_thinking_level("high", ReasoningSupport(False, False, False, False)) is None

    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama")
    buf = StringIO()
    session.console = Console(file=buf, force_terminal=False)
    session._reasoning_support = _menu_support()
    session._reasoning_support_key = ("groq", "llama")
    session._ensure_model_resolved = lambda: None  # type: ignore[method-assign]

    session._apply_thinking_level("xhigh")
    assert session.state.reasoning == "thinking:high"
    out = strip_ansi(buf.getvalue())
    assert "xhigh unavailable" in out and "high" in out

    session._apply_thinking_level("high")
    assert session.state.reasoning == "thinking:high"

def test_prewarm_litellm_idempotent_and_daemon() -> None:
    import sys

    from kite.models import litellm_model

    litellm_model.prewarm_litellm()
    first = litellm_model._prewarm_thread
    litellm_model.prewarm_litellm()
    assert litellm_model._prewarm_thread is first
    if first is None:
        assert "litellm" in sys.modules  # already warm: no thread needed
        return
    assert first.daemon is True
    first.join(timeout=90.0)
    assert "litellm" in sys.modules
