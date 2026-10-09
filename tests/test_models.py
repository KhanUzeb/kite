from __future__ import annotations

from types import SimpleNamespace

import pytest

from kite.models.litellm_model import LitellmModel, StreamStalledError
from kite.models.reasoning import ReasoningSupport, looks_like_reasoning_error, looks_like_temperature_reasoning_error
from kite.models.retry import is_transient_provider_error
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


@pytest.mark.parametrize("raw", [None, {"supported_parameters": ["reasoning_effort"]}])
def test_model_capabilities_wait_for_first_request(kite_home, monkeypatch, raw) -> None:
    import builtins
    import sys
    from threading import current_thread

    from kite.models import reasoning
    from kite.providers import capabilities
    from kite.providers.list_models import RemoteModel
    from kite.providers.resolve import resolve_model
    from kite.tools import ToolRegistry

    resolved = resolve_model(provider="openai", model="deferred-capabilities-test")
    if raw is not None:
        from dataclasses import replace

        resolved = replace(resolved, raw=raw)
    monkeypatch.setattr(reasoning, "_cache", {})
    monkeypatch.setattr(reasoning, "_litellm_reasoning_params", reasoning._litellm_reasoning_params.__wrapped__)
    param_calls = []

    def supported_params(model, provider):
        param_calls.append((model, provider))
        return frozenset({"tools", "parallel_tool_calls"})

    # Stub below the reasoning detector, but above imports and the shared LRU.
    # Replacing sys.modules can race an earlier test's in-flight prewarm import.
    monkeypatch.setattr(capabilities, "_litellm_openai_params", supported_params)
    lookups = []

    def find_remote(provider, model, **_kwargs):
        lookups.append((provider, model))
        return RemoteModel(id=model, raw={"supported_parameters": ["reasoning_effort"]})

    monkeypatch.setattr(sys.modules["kite.providers.list_models"], "find_remote_model", find_remote)
    original_import = builtins.__import__
    owner_thread = current_thread()

    def no_litellm(name, *args, **kwargs):
        if current_thread() is owner_thread and (name == "litellm" or name.startswith("litellm.")):
            pytest.fail("model construction imported LiteLLM")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_litellm)
    model = LitellmModel(resolved, registry=ToolRegistry(), reasoning="fast:low")
    assert not lookups
    assert not param_calls
    assert reasoning.peek_reasoning(resolved.provider, resolved.model) is None
    monkeypatch.setattr(builtins, "__import__", original_import)
    request = model._completion_kwargs([], stream=False)
    assert request["reasoning_effort"] == "low"
    assert request["parallel_tool_calls"] is True
    assert reasoning.peek_reasoning(resolved.provider, resolved.model) is model.reasoning_support
    assert param_calls == [(resolved.litellm_model, "openai")] * 2
    # Evict shared support: a repeat request must use the instance cache, not
    # merely look cached because detect_reasoning's process cache is warm.
    reasoning._cache.clear()
    assert model._completion_kwargs([], stream=False) == request
    assert param_calls == [(resolved.litellm_model, "openai")] * 2
    assert lookups == ([] if raw is not None else [("openai", "deferred-capabilities-test")])


def test_completion_kwargs_temperature_without_reasoning() -> None:
    request = _model()._completion_kwargs([], stream=True)

    assert "temperature" not in request
    assert request["reasoning_effort"] == "low"

    plain = _model(temperature=0.0, mode="off")
    plain.reasoning_support = ReasoningSupport(False, False, False, False)

    plain_request = plain._completion_kwargs([], stream=True)

    assert plain_request["temperature"] == 0.0

    # Only the agent loop retries: nested provider retries multiply delays.
    assert request["num_retries"] == 0
    assert plain._completion_kwargs([], stream=False)["num_retries"] == 0


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


def test_stream_stall_falls_back_to_blocking() -> None:
    model = _model()
    calls: list[str] = []

    def stalled_stream(_messages: list[dict], *, overrides=None) -> dict:
        calls.append("stream")
        raise StreamStalledError("stream stalled: no data for 30s")

    def blocking(_messages: list[dict], *, overrides=None, timeout_s=None) -> dict:
        calls.append("blocking")
        assert timeout_s == 30.0
        return {"role": "assistant", "content": "done"}

    model._query_stream = stalled_stream  # type: ignore[method-assign]
    model._query_blocking = blocking  # type: ignore[method-assign]
    assert model._query_stream_with_fallback([]) == {"role": "assistant", "content": "done"}
    assert calls == ["stream", "blocking"]


def test_stream_open_timeout_uses_one_short_blocking_recovery() -> None:
    model = _model()
    calls: list[str] = []

    def timed_out(_messages: list[dict], *, overrides=None) -> dict:
        calls.append("stream")
        raise TimeoutError("provider request timed out after 30s without responding")

    def blocking(_messages: list[dict], *, overrides=None, timeout_s=None) -> dict:
        calls.append("blocking")
        assert timeout_s == 30.0
        return {"role": "assistant", "content": "Hello!"}

    model._query_stream = timed_out  # type: ignore[method-assign]
    model._query_blocking = blocking  # type: ignore[method-assign]
    assert model._query_stream_with_fallback([])["content"] == "Hello!"
    assert calls == ["stream", "blocking"]


def test_partial_stream_stall_does_not_append_a_second_answer() -> None:
    model = _model()
    model._last_stream_emitted_answer = True

    def stalled(_messages: list[dict], *, overrides=None) -> dict:
        raise StreamStalledError("stream stalled after partial answer")

    def blocking(*_args, **_kwargs) -> dict:
        pytest.fail("blocking fallback would append a duplicate answer")

    model._query_stream = stalled  # type: ignore[method-assign]
    model._query_blocking = blocking  # type: ignore[method-assign]
    with pytest.raises(StreamStalledError, match="partial answer"):
        model._query_stream_with_fallback([])


def test_stream_iterator_closes_transport_when_poll_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    import queue
    from unittest.mock import MagicMock

    from kite.models import litellm_model as lm

    class EmptyQueue:
        def get(self, *, timeout):
            raise queue.Empty

    class CloseableStream:
        closed = False

        def __iter__(self):
            return iter(())

        def close(self):
            self.closed = True

    stream = CloseableStream()
    monkeypatch.setattr(lm, "threading", SimpleNamespace(Thread=MagicMock()))
    monkeypatch.setattr(queue, "Queue", EmptyQueue)

    def timeout():
        raise TimeoutError("test timeout")

    with pytest.raises(TimeoutError, match="test timeout"):
        list(lm._iter_stream_chunks(stream, should_stop=lambda: False, poll=timeout))
    assert stream.closed


def test_stream_opening_uses_first_token_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    model.timeout_seconds = 180
    model.resolved = SimpleNamespace(provider="chatgpt", model="gpt-5.6-luna")
    seen: dict = {}
    failure = RuntimeError("synthetic request failure")

    def open_stream(**kwargs):
        seen.update(kwargs)
        raise failure

    monkeypatch.setattr(model, "_bounded_completion", open_stream)
    model.on_event = lambda _event: None
    with pytest.raises(RuntimeError, match="synthetic request failure"):
        model._query_stream([])

    assert seen["stream"] is True
    assert seen["timeout_s"] == 30.0


def test_stream_stall_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty pump queue still polls the first-token deadline without sleeping."""
    import queue
    from unittest.mock import MagicMock

    from kite.models import litellm_model as lm

    clock = [0.0]
    polls = []

    class EmptyStreamQueue:
        def get(self, *, timeout):
            polls.append(timeout)
            clock[0] += 0.5
            if clock[0] > 5:
                pytest.fail("empty stream queue did not check the stall deadline")
            raise queue.Empty

    # Leave the pump pending, just as when the provider is blocked in __next__.
    # The consumer loop and its real timeout callback still run normally.
    monkeypatch.setattr(lm, "threading", SimpleNamespace(Thread=MagicMock()))
    monkeypatch.setattr(queue, "Queue", EmptyStreamQueue)
    monkeypatch.setattr(lm, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    model = _model()
    model.resolved = SimpleNamespace(provider="nvidia", model="test-model")
    monkeypatch.setattr(model, "_bounded_completion", lambda **_: iter(()))
    model.timeout_seconds = 5
    events = []
    model.on_event = events.append
    model.should_stop = lambda: False

    with pytest.raises(StreamStalledError, match="stream stalled") as exc_info:
        model._query_stream([{"role": "user", "content": "hi"}])

    assert clock[0] == 4.5, "stall at four seconds must beat the five-second overall timeout"
    assert len(polls) == 9
    assert not is_transient_provider_error(exc_info.value)
    assert [(event.kind, event.payload.get("ok")) for event in events] == [
        ("stream_start", None), ("stream_end", False)
    ]


def test_kite_internal_timeouts_never_retry() -> None:
    """Kite's own bounded timeouts fail fast; provider timeouts remain retryable."""
    assert not is_transient_provider_error(TimeoutError("stream timed out after 5s without completing"))
    assert not is_transient_provider_error(StreamStalledError("stream stalled: no data for 30s"))
    assert not is_transient_provider_error(TimeoutError("provider request timed out after 180s without responding"))
    assert not is_transient_provider_error(TimeoutError("provider call timed out after 420s without responding"))
    assert is_transient_provider_error(TimeoutError("connection timed out"))
    assert is_transient_provider_error(TimeoutError("Read timed out."))
    assert not is_transient_provider_error(RuntimeError("provider unavailable"))


def test_peek_reasoning_cache_only(monkeypatch) -> None:
    from kite.models import reasoning

    monkeypatch.setattr(reasoning, "_cache", {})
    key = ("peek-provider-xyz", "peek-model-xyz")
    assert reasoning.peek_reasoning(*key) is None
    support = ReasoningSupport(False, False, False, False)
    reasoning._cache[key] = support
    assert reasoning.peek_reasoning("  peek-provider-xyz ", "peek-model-xyz") is support


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


def test_token_efficiency_report_and_routing(monkeypatch) -> None:
    import sys

    from kite.context.token_report import breakdown_request, price_weighted_cost, rank_opportunities, summarize_run
    from kite.models.routing import route_turn

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(model_cost={}))

    msgs = [
        {"role": "user", "content": "# Setup (reference — not the task)\nx"},
        {"role": "assistant", "content": "hi", "tool_calls": [{"id": "1", "function": {"name": "read"}}]},
        {"role": "user", "content": "next"},
    ]
    breakdown = breakdown_request(system="sys", tool_schemas=[{"function": {"name": "read"}}], messages=msgs)
    assert breakdown.static_tokens == breakdown.system_tokens + breakdown.tool_tokens
    assert breakdown.total_tokens == sum((
        breakdown.static_tokens, breakdown.setup_tokens, breakdown.history_tokens
    ))
    assert sum(breakdown.shares.values()) == pytest.approx(1.0)
    assert price_weighted_cost(
        prompt_tokens=100, completion_tokens=10, cache_read_tokens=90, model_name="unknown-xyz"
    ) == 49
    ranked = rank_opportunities(breakdown)
    assert {name for name, _ in ranked} == {"system", "tools", "setup", "history"}
    assert [score for _, score in ranked] == sorted((score for _, score in ranked), reverse=True)
    run = summarize_run(
        system="sys", messages=msgs, tool_counts={"read": 3},
        tool_errors={"read": 1}, total_runs=2,
    )
    assert run.turns_per_task == 0.5
    assert run.per_tool_use_rate == {"read": 1.0}
    assert run.per_tool_error_rate == {"read": pytest.approx(1 / 3)}

    assert route_turn("hi", enabled=False) == "frontier"
    assert route_turn("hi?", enabled=True) == "cheap"
    assert route_turn("implement auth fix", enabled=True) == "frontier"


def test_usage_tracking_and_litellm_serializer() -> None:
    import warnings

    from pydantic import BaseModel

    from kite.models.litellm_model import _quiet_litellm_usage_serialization

    class Response(BaseModel):
        usage: int

    # Reproduce the malformed typed usage without importing the provider SDK.
    response = Response.model_construct(usage={"prompt_tokens": 1})
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        response.model_dump()

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with _quiet_litellm_usage_serialization():
            response.model_dump()
            warnings.warn("unrelated provider warning", UserWarning, stacklevel=1)
        response.model_dump()

    assert len(seen) == 2
    assert str(seen[0].message) == "unrelated provider warning"
    assert "Pydantic serializer warnings" in str(seen[1].message)

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


def test_thinking_level_clamp_and_apply(workspace, kite_home, monkeypatch) -> None:
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

    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)
    session = ChatSession(cwd=str(workspace), provider="groq", model="llama")
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
    session.display.close()


def test_prewarm_litellm_idempotent_and_daemon(monkeypatch) -> None:
    import sys
    from unittest.mock import MagicMock

    from kite.models import litellm_model

    worker = MagicMock()
    worker.is_alive.return_value = True
    thread = MagicMock(return_value=worker)
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    monkeypatch.setattr(litellm_model, "_prewarm_thread", None)
    monkeypatch.setattr(litellm_model, "threading", SimpleNamespace(Thread=thread))

    litellm_model.prewarm_litellm()
    litellm_model.prewarm_litellm()
    thread.assert_called_once()
    worker.start.assert_called_once_with()
    assert thread.call_args.kwargs["daemon"] is True
    assert litellm_model._prewarm_thread is worker

    # A loaded dependency needs no worker even if the old worker has ended.
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace())
    monkeypatch.setattr(litellm_model, "_prewarm_thread", None)
    litellm_model.prewarm_litellm()
    assert litellm_model._prewarm_thread is None
    thread.assert_called_once()


def test_agy_subscription_turn_is_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    from kite.agent.exceptions import ProviderFault
    from kite.models import litellm_model as lm
    from kite.providers.auth.antigravity_exec import AgyTurn, AntigravityQuotaError

    model = object.__new__(LitellmModel)
    model.resolved = SimpleNamespace(
        provider="antigravity",
        model="gemini-3.7-flash-medium",
        api_key=None,
        spec=SimpleNamespace(auth_kind="oauth", oauth_provider="antigravity", name="antigravity"),
    )
    events: list[str] = []
    model.on_event = lambda e: events.append(e.kind)
    model.should_stop = lambda: False
    model.timeout_seconds = 0
    model.cost = 0.0
    model.last_usage = {}
    assert lm._is_agy_subscription(model.resolved) is True
    assert lm._is_agy_subscription(SimpleNamespace(provider="antigravity", api_key="k")) is False
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace())

    monkeypatch.setattr(
        "kite.providers.auth.antigravity_exec.run_agy_turn",
        lambda **_k: AgyTurn(text="hello", input_tokens=3, output_tokens=2),
    )
    msg = model.query([{"role": "user", "content": "hi"}])
    assert msg["content"] == "hello" and msg["extra"]["actions"] == []
    assert "tool_calls" not in msg and msg["extra"]["cost"] == 0.0
    assert msg["extra"]["usage"]["total_tokens"] == 5
    assert "stream_start" in events and "stream_end" in events

    def _quota(**_k: object) -> AgyTurn:
        raise AntigravityQuotaError("Antigravity subscription quota reached. Resets in 1h")

    monkeypatch.setattr("kite.providers.auth.antigravity_exec.run_agy_turn", _quota)
    with pytest.raises(ProviderFault) as exc_info:
        model.query([{"role": "user", "content": "hi"}])
    assert "quota" in exc_info.value.error.lower()

