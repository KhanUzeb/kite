"""Shared utilities."""

from typing import Any


def bounded_int(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    """Parse a tool's optional integer and clamp it to its supported range."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum:
        return minimum
    if maximum is not None and number > maximum:
        return maximum
    return number
