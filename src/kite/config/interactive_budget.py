"""Resolve interactive chat step/cost floors without overriding user caps."""

from __future__ import annotations

PACKAGE_STEP = 40
PACKAGE_COST = 5.0
DEFAULT_INTERACTIVE_STEP = 80
DEFAULT_INTERACTIVE_COST = 10.0


def resolve_interactive_limits(
    *,
    interactive: bool,
    user_step: int,
    user_cost: float,
    runtime_step: int,
    runtime_cost: float,
    interactive_step: int = DEFAULT_INTERACTIVE_STEP,
    interactive_cost: float = DEFAULT_INTERACTIVE_COST,
    package_step: int = PACKAGE_STEP,
    package_cost: float = PACKAGE_COST,
) -> tuple[int, float]:
    if not interactive:
        return runtime_step, runtime_cost
    step = runtime_step
    cost = runtime_cost
    if user_step == package_step:
        step = max(runtime_step, interactive_step)
    if abs(user_cost - package_cost) < 1e-9:
        cost = max(runtime_cost, interactive_cost)
    return step, cost


def effective_agent_limits(
    *,
    interactive: bool,
    options_step: int | None,
    options_cost: float | None,
    runtime_step: int,
    runtime_cost: float,
    user_step: int,
    user_cost: float,
    interactive_step: int = DEFAULT_INTERACTIVE_STEP,
    interactive_cost: float = DEFAULT_INTERACTIVE_COST,
    long_task: bool = False,
) -> tuple[int, float]:
    step = options_step if options_step is not None else runtime_step
    cost = options_cost if options_cost is not None else runtime_cost
    if long_task:
        if options_step is None:
            step = max(step, 120)
        if options_cost is None:
            cost = max(cost, 25.0)
    if interactive:
        # Apply floors only for dimensions not explicitly set on the harness options.
        floor_step, floor_cost = resolve_interactive_limits(
            interactive=True,
            user_step=user_step,
            user_cost=user_cost,
            runtime_step=runtime_step,
            runtime_cost=runtime_cost,
            interactive_step=interactive_step,
            interactive_cost=interactive_cost,
        )
        if options_step is None:
            step = floor_step if not long_task else max(step, floor_step)
        if options_cost is None:
            cost = floor_cost if not long_task else max(cost, floor_cost)
    return step, cost
