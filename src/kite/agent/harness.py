"""Thin harness wrapper — delegates to AgentRuntime.

Swap internals without forking:

    harness.use("summarizer", my_fn)
    harness.use("model", lambda **kw: MyModel(...))
    harness.on("before_query", lambda messages, **_: messages)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kite.agent.events import Event
from kite.agent.hooks import SLOTS, HarnessSlots, HookBus
from kite.agent.queue import RunMessageQueue
from kite.agent.runtime import AgentRuntime, RuntimeOptions
from kite.config import UserConfig
from kite.memory.session import Session
from kite.tools.jobs import JobRegistry
from kite.tools.store import TodoStore

if TYPE_CHECKING:
    from kite.application.contracts import RunSpec


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
    no_extensions: bool = False
    config_name: str | Path | None = None
    mode: str = "build"
    approval: str = "auto"
    interactive: bool = False
    reasoning: str = "auto"
    role: str = "auto"
    attachments: list | None = None
    execution_mode: str | None = None  # restricted | host
    long_task: bool = False
    memory_in_prompt: bool = False
    goal_objective: str = ""


@dataclass
class Harness:
    config: HarnessConfig = field(default_factory=HarnessConfig)
    user_config: UserConfig | None = None
    slots: HarnessSlots = field(default_factory=HarnessSlots)
    hooks: HookBus = field(default_factory=HookBus)
    extra_tools: list[Any] = field(default_factory=list)
    tool_executor: object | None = None
    policy_engine: object | None = None
    _runtime: AgentRuntime | None = field(default=None, init=False)
    last_session: Session | None = field(default=None, init=False)
    approver: object | None = None
    checkpoints: object | None = None
    todos: TodoStore | None = None
    job_registry: JobRegistry | None = None
    message_queue: RunMessageQueue | None = None
    _extensions_loaded: bool = field(default=False, init=False)

    def use(self, slot: str, impl: Any) -> Harness:
        if slot not in SLOTS:
            raise KeyError(f"unknown slot '{slot}'. known: {', '.join(SLOTS)}")
        setattr(self.slots, slot, impl)
        return self

    def on(self, event: str, fn: Callable) -> Harness:
        self.hooks.on(event, fn)
        return self

    def subscribe(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        if self._runtime is None:
            self._runtime = self._make_runtime()
        return self._runtime.subscribe(listener)

    def _load_extensions(self) -> None:
        if self._extensions_loaded or self.config.no_extensions:
            return
        self._extensions_loaded = True
        from kite.extensions.loader import load_extensions

        load_extensions(self, self.config.cwd or ".")

    def _make_runtime(self) -> AgentRuntime:
        self._load_extensions()
        runtime = AgentRuntime(
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
                reasoning=self.config.reasoning,
                role=self.config.role,
                attachments=self.config.attachments,
                execution_mode=self.config.execution_mode,
                long_task=self.config.long_task,
                memory_in_prompt=self.config.memory_in_prompt,
                goal_objective=self.config.goal_objective,
            ),
            user_config=self.user_config,
        )
        runtime.slots = self.slots
        runtime.hooks = self.hooks
        runtime.extra_tools = self.extra_tools
        if self.job_registry is not None:
            runtime.job_registry = self.job_registry
        return runtime

    def run(self, task: str, *, cancel=None) -> dict:
        self._load_extensions()
        runtime = self._runtime or self._make_runtime()
        self._runtime = runtime
        runtime.slots = self.slots
        runtime.hooks = self.hooks
        runtime.extra_tools = self.extra_tools
        if self.job_registry is not None:
            runtime.job_registry = self.job_registry
        # Always assign: None → runtime creates a fresh CancelToken for this turn.
        runtime.cancel_token = cancel
        if self.approver is not None:
            runtime.approver = self.approver  # type: ignore[assignment]
        if self.checkpoints is not None:
            runtime.checkpoints = self.checkpoints
        if self.todos is not None:
            runtime.todos = self.todos
        if self.tool_executor is not None:
            runtime.tool_executor_override = self.tool_executor
        if self.policy_engine is not None:
            runtime.policy_engine_override = self.policy_engine
        if self.message_queue is not None:
            runtime.message_queue = self.message_queue
        try:
            result = runtime.run(task)
        finally:
            if cancel is None:
                runtime.cancel_token = None
        self.last_session = runtime.last_session
        if self.job_registry is None and runtime.job_registry is not None:
            self.job_registry = runtime.job_registry
        return result

    def request_interrupt(self) -> None:
        if self._runtime is not None:
            self._runtime.request_interrupt()

    def inject_user_message(self, text: str, *, steer: bool = False) -> bool:
        if self._runtime is not None and self._runtime.last_agent is not None:
            return self._runtime.last_agent.inject_user_message(text, steer=steer)
        if self.message_queue is not None:
            return self.message_queue.steer(text) if steer else self.message_queue.enqueue(text)
        return False

    def teardown_jobs(self) -> int:
        if self.job_registry is not None:
            return self.job_registry.kill_all()
        if self._runtime is not None:
            return self._runtime.teardown_jobs()
        return 0

    def to_run_spec(self, task: str) -> RunSpec:
        """Build a canonical RunSpec from the current harness config."""
        from kite.application.adapters.harness import run_spec_from_harness_config

        return run_spec_from_harness_config(self.config, task)
