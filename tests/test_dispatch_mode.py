"""Auto sync/async dispatch inference for subagent orchestration."""

from __future__ import annotations

from kite.agent.dispatch_mode import resolve_dispatch_mode


def test_explicit_background_flag() -> None:
    bg, reason = resolve_dispatch_mode({"prompt": "x", "background": True})
    assert bg is True
    assert reason == "explicit-async"


def test_explicit_wait_false() -> None:
    bg, reason = resolve_dispatch_mode({"prompt": "x", "wait": False})
    assert bg is True
    assert reason == "explicit-async"


def test_parallel_crew_defaults_sync() -> None:
    bg, reason = resolve_dispatch_mode({"prompts": ["a", "b"], "labels": ["x", "y"]})
    assert bg is False
    assert reason == "parallel-crew-sync"


def test_auto_async_from_prompt_wording() -> None:
    bg, reason = resolve_dispatch_mode(
        {"prompt": "Survey routes in the background while I refactor the CLI."}
    )
    assert bg is True
    assert reason == "auto-async"


def test_auto_sync_from_prompt_wording() -> None:
    bg, reason = resolve_dispatch_mode(
        {"prompt": "Map the auth module and report back before continuing."}
    )
    assert bg is False
    assert reason == "auto-sync"


def test_default_sync_when_ambiguous() -> None:
    bg, reason = resolve_dispatch_mode({"prompt": "Explore src/kite/agent"})
    assert bg is False
    assert reason == "default-sync"


def test_background_word_alone_does_not_force_async() -> None:
    bg, reason = resolve_dispatch_mode({"prompt": "Read the background jobs module under src/kite/tools"})
    assert bg is False
    assert reason == "default-sync"


def test_dispatch_hint_for_auto_modes() -> None:
    from kite.agent.dispatch_mode import dispatch_hint

    assert "async" in dispatch_hint("auto-async")
    assert "sync" in dispatch_hint("parallel-crew-sync")
