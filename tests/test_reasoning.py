"""Thinking / fast levels from advertised API efforts."""

from __future__ import annotations

from kite.cli.slash import CommandIndex, SlashSpec
from kite.models.reasoning import (
    ReasoningSupport,
    apply_reasoning,
    encode_reasoning,
    parse_mode,
    reasoning_badge,
    split_reasoning,
)
from kite.ui.complete import _PT, SlashCompleter, _visible_specs, effort_menu
from kite.ui.state import SessionUiState
from kite.ui.status import format_status_tail


def _both(**kwargs) -> ReasoningSupport:
    defaults: dict = dict(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high", "extra_body": {"reasoning": {"effort": "high"}}},
        fast_kwargs={"reasoning_effort": "low"},
        efforts=("none", "low", "medium", "high"),
    )
    defaults.update(kwargs)
    return ReasoningSupport(**defaults)


def test_levels_split_by_thinking_and_fast() -> None:
    info = _both()
    assert info.can_both
    assert info.thinking_levels() == ("medium", "high")
    assert info.fast_levels() == ("low",)
    assert info.default_effort("thinking") == "high"
    assert info.default_effort("fast") == "low"


def test_no_effort_list_uses_on() -> None:
    info = _both(efforts=())
    assert info.thinking_levels() == ("on",)
    assert info.fast_levels() == ("on",)


def test_split_and_encode() -> None:
    assert split_reasoning("thinking:high") == ("thinking", "high")
    assert parse_mode("thinking:high") == "thinking"
    assert parse_mode("high") == "thinking"
    assert split_reasoning("high") == ("thinking", "high")
    assert split_reasoning("low") == ("fast", "low")
    assert encode_reasoning("thinking", "high") == "thinking:high"
    assert encode_reasoning("thinking", "on") == "thinking"
    assert reasoning_badge("thinking:high") == "thinking high"


def test_apply_reasoning_uses_picked_level() -> None:
    info = _both()
    out = apply_reasoning({}, info, "thinking", effort="medium")
    assert out["reasoning_effort"] == "medium"
    assert out["extra_body"]["reasoning"]["effort"] == "medium"


def test_nemotron_heuristic_enables_thinking_fast() -> None:
    from kite.models.reasoning import detect_reasoning

    info = detect_reasoning("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b", refresh=True)
    assert info.supported
    assert info.can_both
    assert info.thinking_levels()


def test_thinking_fast_hidden_unless_api_has_both() -> None:
    specs = {
        "thinking": SlashSpec("thinking", "control", "builtin", "t"),
        "fast": SlashSpec("fast", "control", "builtin", "f"),
        "reasoning": SlashSpec("reasoning", "control", "builtin", "r"),
        "plan": SlashSpec("plan", "control", "builtin", "p"),
    }
    index = CommandIndex(specs=specs)
    only_think = ReasoningSupport(True, False, True, True)
    names = {s.name for s in _visible_specs(index, support=only_think)}
    assert "thinking" not in names
    assert "fast" not in names
    assert "reasoning" in names
    assert "plan" in names
    both = _both()
    names = {s.name for s in _visible_specs(index, support=both)}
    assert {"thinking", "fast", "reasoning", "plan"} <= names


def test_thinking_dropdown_lists_thinking_levels() -> None:
    info = _both()
    levels = [name for name, _ in effort_menu(info, "thinking")]
    assert "high" in levels
    assert "medium" in levels
    assert "low" not in levels


    if not _PT:
        return
    completer = SlashCompleter(lambda: CommandIndex(), reasoning_info=lambda: info)

    class _Doc:
        def __init__(self, text: str) -> None:
            self.text_before_cursor = text

    hits = list(completer.get_completions(_Doc("/thinking "), None))
    values = [c.text for c in hits]
    assert "high" in values
    assert "medium" in values


def test_footer_shows_thinking_level() -> None:
    state = SessionUiState(provider="openrouter", model="gpt", reasoning="thinking:high")
    tail = format_status_tail(state)
    assert "thinking high" in tail
    assert "thinking:high" not in tail


def test_effort_menu_empty_without_both() -> None:
    info = ReasoningSupport(True, False, True, True, efforts=("low", "high"))
    assert effort_menu(info, "fast") == []
    assert info.thinking_levels() == ("high",)
