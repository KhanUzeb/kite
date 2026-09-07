"""Pi-style internal slots + lifecycle hooks.

Tweak the harness without forking the loop:

    h = Harness(...)
    h.use("summarizer", my_summarizer)
    h.use("model", my_model_factory)
    h.on("before_query", lambda messages, **_: messages[-40:])

Known slots: model, tools, env, summarizer, memory, assemble_system
Events: before_run, after_prepare, before_query, after_query,
        before_tool, after_tool, before_compact, after_compact, after_run
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SLOTS = ("model", "tools", "env", "summarizer", "memory", "assemble_system")

HookFn = Callable[..., Any]


@dataclass
class HarnessSlots:
    model: Callable[..., Any] | None = None
    tools: Callable[..., Any] | None = None
    env: Callable[..., Any] | None = None
    summarizer: Callable[[list[dict]], str] | None = None
    memory: Any = None
    assemble_system: Callable[..., str] | None = None


@dataclass
class HookBus:
    _subs: dict[str, list[HookFn]] = field(default_factory=dict)

    def on(self, event: str, fn: HookFn) -> HookFn:
        self._subs.setdefault(event, []).append(fn)
        return fn

    def fire(self, event: str, **payload: Any) -> None:
        for fn in list(self._subs.get(event, [])):
            fn(**payload)

    def call(self, event: str, value: Any, **extra: Any) -> Any:
        """Pipeline: each listener may return a replacement; None means keep."""
        for fn in list(self._subs.get(event, [])):
            out = fn(value, **extra) if extra else fn(value)
            if out is not None:
                value = out
        return value
