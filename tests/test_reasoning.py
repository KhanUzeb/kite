"""Thinking / fast levels from advertised API efforts."""

from __future__ import annotations

from kite.cli.slash import CommandIndex, SlashSpec
from kite.models.reasoning import ReasoningSupport, apply_reasoning, encode_reasoning, split_reasoning
from kite.ui.complete import _visible_specs


def _both(**kwargs) -> ReasoningSupport:
    defaults: dict = dict(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high"},
        fast_kwargs={"reasoning_effort": "low"},
        efforts=("none", "low", "medium", "high"),
    )
    defaults.update(kwargs)
    return ReasoningSupport(**defaults)


def test_levels_split_by_thinking_and_fast() -> None:
    info = _both()
    assert info.thinking_levels() == ("medium", "high")
    assert info.fast_levels() == ("low",)


def test_split_and_encode() -> None:
    assert split_reasoning("thinking:high") == ("thinking", "high")
    assert split_reasoning("low") == ("fast", "low")
    assert encode_reasoning("thinking", "high") == "thinking:high"


def test_apply_reasoning_uses_picked_level() -> None:
    info = _both()
    out = apply_reasoning({}, info, "thinking", effort="medium")
    assert out["reasoning_effort"] == "medium"


def test_thinking_fast_hidden_unless_api_has_both() -> None:
    specs = {
        "thinking": SlashSpec("thinking", "control", "builtin", "t"),
        "fast": SlashSpec("fast", "control", "builtin", "f"),
        "reasoning": SlashSpec("reasoning", "control", "builtin", "r"),
    }
    index = CommandIndex(specs=specs)
    only_think = ReasoningSupport(True, False, True, True)
    names = {s.name for s in _visible_specs(index, support=only_think)}
    assert "thinking" not in names
    assert "reasoning" in names
    both = _both()
    names = {s.name for s in _visible_specs(index, support=both)}
    assert {"thinking", "fast", "reasoning"} <= names
