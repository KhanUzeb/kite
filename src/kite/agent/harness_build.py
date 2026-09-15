"""Central harness config builder — one shape for CLI, REPL, headless, and nested workers."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from kite.agent.harness import HarnessConfig

_KNOWN_FIELDS = frozenset(f.name for f in fields(HarnessConfig))


def _validate_kwargs(kwargs: dict[str, Any]) -> None:
    unknown = sorted(k for k in kwargs if k not in _KNOWN_FIELDS)
    if unknown:
        raise TypeError(f"unknown harness config field(s): {', '.join(unknown)}")


def harness_config_from_dict(data: dict[str, Any]) -> HarnessConfig:
    """Build ``HarnessConfig`` from a mapping — single validation point."""
    kwargs = dict(data)
    _validate_kwargs(kwargs)
    return HarnessConfig(**kwargs)


def build_harness_config(**kwargs: Any) -> HarnessConfig:
    """Build ``HarnessConfig`` for any harness entry point (passthrough)."""
    return harness_config_from_dict(kwargs)
