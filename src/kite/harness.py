"""Thin harness wrapper — delegates to AgentRuntime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kite.config import UserConfig
from kite.events import Event
from kite.memory.session import Session
from kite.runtime import AgentRuntime, RuntimeOptions
from kite.tools.store import TodoStore


@dataclass
class HarnessConfig:
    provider: str | None = None
    model_name: str | None = None
    cwd: str | None = None
    step_limit: int | None = None
    cost_limit: float | None = None
    wall_time_limit_seconds: int = 0
    output_path: Path | None = None
    system_prompt: str | None = None
    session_id: str | None = None
    resume: bool = False
    follow_up: str | None = None
    label: str = ""
    no_context: bool = False
    no_compact: bool = False
    no_guardrails: bool = False
    config_name: str | Path | None = None
    mode: str = "build"
    approval: str = "auto"
    interactive: bool = False


@dataclass
class Harness:
    config: HarnessConfig = field(default_factory=HarnessConfig)
    user_config: UserConfig | None = None
    _runtime: AgentRuntime | None = field(default=None, init=False)
    last_session: Session | None = field(default=None, init=False)
    approver: object | None = None
    checkpoints: object | None = None
    todos: TodoStore | None = None

    def subscribe(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        # Lazily create runtime so listeners attach before run
        if self._runtime is None:
            self._runtime = self._make_runtime()
        return self._runtime.subscribe(listener)

    def _make_runtime(self) -> AgentRuntime:
        return AgentRuntime(
            RuntimeOptions(
                provider=self.config.provider,
                model=self.config.model_name,
                cwd=self.config.cwd,
                config_name=self.config.config_name,
                system_prompt_override=self.config.system_prompt,
                session_id=self.config.session_id,
                resume=self.config.resume,
                follow_up=self.config.follow_up,
                label=self.config.label,
                no_context=self.config.no_context,
                no_compact=self.config.no_compact,
                no_guardrails=self.config.no_guardrails,
                output_path=self.config.output_path,
                step_limit=self.config.step_limit,
                cost_limit=self.config.cost_limit,
                wall_time_limit_seconds=self.config.wall_time_limit_seconds or None,
                mode=self.config.mode,
                approval=self.config.approval,
                interactive=self.config.interactive,
            ),
            user_config=self.user_config,
        )

    def run(self, task: str) -> dict:
        runtime = self._runtime or self._make_runtime()
        self._runtime = runtime
        if self.approver is not None:
            runtime.approver = self.approver  # type: ignore[assignment]
        if self.checkpoints is not None:
            runtime.checkpoints = self.checkpoints
        if self.todos is not None:
            runtime.todos = self.todos
        result = runtime.run(task)
        self.last_session = runtime.last_session
        return result
