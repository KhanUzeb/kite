"""Interactive chat budget floors vs package defaults."""

from __future__ import annotations

from kite.config.interactive_budget import effective_agent_limits, resolve_interactive_limits
from kite.context.window import DEFAULT_COMPACT_RATIO


def test_interactive_floors_on_package_defaults() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=40,
        user_cost=5.0,
        runtime_step=40,
        runtime_cost=5.0,
    )
    assert steps == 80
    assert cost == 10.0


def test_honor_explicit_lower_user_caps() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=20,
        user_cost=1.0,
        runtime_step=20,
        runtime_cost=1.0,
    )
    assert steps == 20
    assert cost == 1.0


def test_non_interactive_unchanged() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=False,
        user_step=40,
        user_cost=5.0,
        runtime_step=40,
        runtime_cost=5.0,
    )
    assert steps == 40
    assert cost == 5.0


def test_default_compact_ratio_is_075() -> None:
    assert DEFAULT_COMPACT_RATIO == 0.75


def test_effective_agent_limits_interactive_defaults() -> None:
    steps, cost = effective_agent_limits(
        interactive=True,
        options_step=None,
        options_cost=None,
        runtime_step=40,
        runtime_cost=5.0,
        user_step=40,
        user_cost=5.0,
        interactive_step=80,
        interactive_cost=10.0,
        long_task=False,
    )
    assert steps == 80
    assert cost == 10.0


def test_effective_agent_limits_long_task() -> None:
    steps, cost = effective_agent_limits(
        interactive=False,
        options_step=None,
        options_cost=None,
        runtime_step=40,
        runtime_cost=5.0,
        user_step=40,
        user_cost=5.0,
        interactive_step=80,
        interactive_cost=10.0,
        long_task=True,
    )
    assert steps == 120
    assert cost == 25.0


def test_effective_agent_limits_explicit_options_win() -> None:
    steps, cost = effective_agent_limits(
        interactive=True,
        options_step=15,
        options_cost=2.0,
        runtime_step=40,
        runtime_cost=5.0,
        user_step=40,
        user_cost=5.0,
        interactive_step=80,
        interactive_cost=10.0,
        long_task=False,
    )
    assert steps == 15
    assert cost == 2.0
