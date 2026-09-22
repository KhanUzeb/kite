"""Performance helper caches — no live LLM."""

from __future__ import annotations

from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.runtime import AgentRuntime, RuntimeOptions
from kite.context.window import estimate_tool_schema_tokens, estimate_usage
from kite.models.cache import PromptCacheManager
from kite.providers.capabilities import _litellm_openai_params, model_supports_parallel_tool_calls
from kite.providers.resolve import ResolvedModel


def test_estimate_usage_and_compactor_measure() -> None:
    schemas = [{"name": "read", "parameters": {"type": "object"}}]
    precomputed = estimate_tool_schema_tokens(schemas)
    usage = estimate_usage(system="sys", messages=[], tool_tokens=precomputed, window=1000)
    assert usage.tool_tokens == precomputed

    calls: list[str] = []

    def on_event(event):
        calls.append(event.kind)

    compactor = LoopCompactor(
        CompactionConfig(window=10_000),
        system="system prompt",
        tool_schemas=[{"name": "read", "parameters": {}}],
        on_event=on_event,
    )
    messages = [{"role": "user", "content": "hi"}]
    first = compactor.measure(messages)
    second = compactor.measure(messages)
    assert first is second
    assert calls.count("context") == 1


def test_prompt_cache_manager_memoize_and_stable_prefix() -> None:
    messages = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "go"}]
    disabled = PromptCacheManager(provider="anthropic", enabled=False)
    a = disabled.prepare(messages)
    b = disabled.prepare(messages)
    assert a is b

    mgr = PromptCacheManager(provider="anthropic", enabled=True)
    first = mgr.prepare(messages)
    assert mgr.prepare(messages) is first
    assert first[0]["content"][0].get("cache_control")
    grown = [*messages, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
    second = mgr.prepare(grown)
    assert second is not first and len(second) == len(grown) and mgr.prepare(grown) is second


def test_runtime_prepare_static_and_litellm_cache() -> None:
    from unittest.mock import MagicMock, patch

    from kite.config import UserConfig

    resolved = MagicMock(provider="test", model="m", context_window=128_000)
    rt = AgentRuntime(options=RuntimeOptions(cwd=".", no_context=True, label="test"))
    ucfg = UserConfig.load()
    cwd = "."
    with patch("kite.agent.runtime.resolve_model", return_value=resolved):
        with patch("kite.providers.resolve.missing_credentials", return_value=None):
            with patch("kite.providers.resolve.missing_model", return_value=None):
                first = rt._prepare_static(ucfg, cwd)
                second = rt._prepare_static(ucfg, cwd)
    assert first[0] is second[0]
    assert first[1] is second[1]
    rt.invalidate_prepare_cache()
    with patch("kite.agent.runtime.resolve_model", return_value=resolved):
        with patch("kite.providers.resolve.missing_credentials", return_value=None):
            with patch("kite.providers.resolve.missing_model", return_value=None):
                third = rt._prepare_static(ucfg, cwd)
    assert third[1].model == first[1].model

    # Empty model returns None without calling network-heavy paths twice.
    assert _litellm_openai_params("", "") is None
    info = _litellm_openai_params.cache_info()
    assert info.hits + info.misses >= 1


def test_parallel_tool_calls_and_resolved_model() -> None:
    raw = {"capabilities": {"tools": True, "parallel_tool_calls": True}}
    assert model_supports_parallel_tool_calls(provider="test", model="m", raw=raw) is True
    assert "raw" in ResolvedModel.__dataclass_fields__
