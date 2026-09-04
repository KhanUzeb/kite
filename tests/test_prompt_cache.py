"""Prompt cache manager — session stats and completion persistence."""

from __future__ import annotations

from types import SimpleNamespace

from kite.agent.runtime import AgentRuntime, RuntimeOptions
from kite.memory.session import create_session
from kite.models.cache import PromptCacheManager, CacheStats


def test_disabled_cache_summary_is_zero_valued() -> None:
    mgr = PromptCacheManager("anthropic", enabled=False)
    summary = mgr.summary()
    assert summary["cache_hit_tokens"] == 0
    assert summary["calls"] == 0
    assert "prefix_hash" in summary


def test_record_accumulates_session_stats() -> None:
    mgr = PromptCacheManager("anthropic", enabled=True)

    class _Usage:
        prompt_tokens = 100
        completion_tokens = 20
        cache_read_input_tokens = 80

    mgr.record(_Usage())
    summary = mgr.summary()
    assert summary["cache_hit_tokens"] == 80
    assert summary["prompt_tokens"] == 100
    assert summary["calls"] == 1


def test_session_interface_not_stats_attribute() -> None:
    mgr = PromptCacheManager("openai", enabled=True)
    assert hasattr(mgr, "session")
    assert not hasattr(mgr, "stats")


def test_runtime_persist_session_stats_uses_session_not_stats(kite_home, tmp_path) -> None:
    runtime = AgentRuntime(RuntimeOptions(cwd=str(tmp_path)))
    session = create_session(task="cache", cwd=str(tmp_path), provider="groq", model="test")
    cache = PromptCacheManager("groq", enabled=True)
    cache.session = CacheStats(cache_read_tokens=42, calls=1)
    agent = SimpleNamespace(
        model=SimpleNamespace(prompt_cache=cache),
        last_usage_estimate=None,
        mode=None,
        approval=None,
        tool_call_count=0,
        tool_counts={},
        n_calls=1,
        cost=0.0,
    )
    runtime._persist_session_stats(session, {"exit_status": "Submitted"}, agent=agent)
    from kite.memory.session_analytics import load_session_stats

    saved = load_session_stats(session.id)
    assert saved is not None
    assert saved.cache_hit_tokens == 42
