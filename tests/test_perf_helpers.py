"""Performance helper caches — no live LLM."""

from __future__ import annotations

from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.runtime import AgentRuntime, RuntimeOptions
from kite.context.window import estimate_usage
from kite.models.cache import PromptCacheManager


def test_compactor_reuses_measurement_without_duplicate_events() -> None:
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


def test_compactor_incremental_accounting_and_history_replacement(monkeypatch) -> None:
    from kite.context.window import estimate_message_tokens

    measured: list[dict] = []

    def count_message(message):
        measured.append(message)
        return estimate_message_tokens(message)

    monkeypatch.setattr("kite.agent.compaction.estimate_message_tokens", count_message)
    compactor = LoopCompactor(CompactionConfig(), system="system")
    messages = [{"role": "system", "content": "system"}]
    additions = [
        {"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url"}]},
        {"role": "assistant", "content": "", "extra": {"reasoning": "thinking"},
         "tool_calls": [{"id": "1", "function": {"name": "read", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "name": "read", "content": "file contents"},
        {"role": "exit", "content": "done"},
    ]
    for message in additions:
        messages.append(message)
        assert compactor.measure(messages, append_only=True) == estimate_usage(system="system", messages=messages)
    assert len(measured) == 4  # Every non-exit message is estimated once, not once per turn.
    compactor.measure(messages, append_only=True)
    assert len(measured) == 4

    # Arbitrary callers can mutate content at the same count; the default path remeasures.
    messages[1]["content"] = "changed " * 500
    assert compactor.measure(messages) == estimate_usage(system="system", messages=messages)
    replaced = [{"role": "user", "content": "replacement " * 20}, *messages[1:]]
    assert compactor.measure(replaced, append_only=True) == estimate_usage(system="system", messages=replaced)
    del replaced[1:]
    assert compactor.measure(replaced, append_only=True) == estimate_usage(system="system", messages=replaced)


def test_compactor_remeasures_in_place_history_hooks() -> None:
    from kite.agent.hooks import HookBus
    from kite.agent.loop import DefaultAgent

    hooks = HookBus()
    agent = DefaultAgent(object(), object(), hooks=hooks, system_prompt="system", auto_compact=False)
    agent.messages = [{"role": "user", "content": "small"}]
    agent._maybe_compact()
    hooks.on("before_compact", lambda messages: messages[0].update(content="large " * 100))
    agent._maybe_compact()
    assert agent.last_usage_estimate == estimate_usage(system="system", messages=agent.messages)


def test_prompt_cache_never_reuses_stale_turns() -> None:
    for enabled in (False, True):
        manager = PromptCacheManager(provider="anthropic", enabled=enabled)
        messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "# Setup context"}]
        first = manager.prepare(messages)
        if enabled:
            assert first[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        else:
            assert manager.prepare(messages) is first
        for turn in range(3):
            messages = [*messages, {"role": "assistant", "content": "reading", "tool_calls": [
                {"id": str(turn), "function": {"name": "read", "arguments": '{"path":"a.py"}'}}
            ]}, {"role": "tool", "content": "identical output", "tool_call_id": str(turn)}]
            prepared = manager.prepare(messages)
            assert len(prepared) == len(messages)
            assert prepared[-1]["tool_call_id"] == str(turn)
            assert manager.prepare(messages) == prepared
        messages[2]["tool_calls"][0]["function"]["arguments"] = '{"path":"changed.py"}'
        messages[1]["content"] = "# Setup " + "x" * 500 + "changed"
        prepared = manager.prepare(messages)
        assert prepared[2]["tool_calls"][0]["function"]["arguments"] == '{"path":"changed.py"}'
        assert prepared[1]["content"] == (
            [{"type": "text", "text": messages[1]["content"], "cache_control": {"type": "ephemeral"}}]
            if enabled else messages[1]["content"]
        )
        assert isinstance(messages[0]["content"], str)  # Breakpoints must not mutate history.


def test_runtime_prepare_cache_reuses_and_invalidates(workspace, kite_home, monkeypatch) -> None:
    from types import SimpleNamespace

    from kite.config import UserConfig

    resolved_models = []

    def resolve_model(**kwargs):
        resolved = SimpleNamespace(provider="ollama", model=kwargs["model"] or "initial")
        resolved_models.append(resolved)
        return resolved

    monkeypatch.setattr("kite.agent.runtime.resolve_model", resolve_model)
    monkeypatch.setattr("kite.agent.runtime.load_skills", lambda *_args, **_kwargs: [])
    cwd = str(workspace)
    rt = AgentRuntime(options=RuntimeOptions(cwd=cwd, no_context=True, label="test"))
    config = UserConfig()
    first = rt._prepare_static(config, cwd)
    second = rt._prepare_static(config, cwd)
    assert first[0] is second[0] and first[1] is second[1]
    assert len(resolved_models) == 1

    rt.invalidate_prepare_cache()
    third = rt._prepare_static(config, cwd)
    assert third[1] is not first[1]
    assert len(resolved_models) == 2

    rt.options.model = "changed-model"
    changed = rt._prepare_static(config, cwd)
    assert changed[1].model == "changed-model"
    assert rt.last_resolved is changed[1]
    assert len(resolved_models) == 3
