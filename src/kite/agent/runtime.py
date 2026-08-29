"""Agent runtime — assembles config, prompts, skills, tools, guardrails, loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.loop import DefaultAgent
from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode, tools_for_mode
from kite.cli.slash import expand_prompt_slash
from kite.config import AgentRuntimeConfig, UserConfig, ensure_home, load_runtime_config
from kite.context.discovery import gather_project_context
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.memory.session import Session, create_session, load_session
from kite.memory.store import MemoryStore
from kite.models.litellm_model import LitellmModel
from kite.prompts import assemble_instance_prompt, assemble_system_prompt, load_prompt_template
from kite.providers.resolve import ResolvedModel, missing_credentials, missing_model, resolve_model
from kite.skills.loader import load_skills
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools
from kite.tools.store import TodoStore


@dataclass
class RuntimeOptions:
    provider: str | None = None
    model: str | None = None
    cwd: str | None = None
    config_name: str | Path | None = None
    system_prompt_override: str | None = None
    session_id: str | None = None
    resume: bool = False
    follow_up: str | None = None
    label: str = ""
    no_context: bool = False
    no_compact: bool = False
    no_guardrails: bool = False
    output_path: Path | None = None
    step_limit: int | None = None
    cost_limit: float | None = None
    wall_time_limit_seconds: int | None = None
    mode: str = "build"
    approval: str = "auto"
    interactive: bool = False


@dataclass
class AgentRuntime:
    """High-level façade used by the CLI / harness."""

    options: RuntimeOptions = field(default_factory=RuntimeOptions)
    user_config: UserConfig | None = None
    _listeners: list[Callable[[Event], None]] = field(default_factory=list, init=False)
    last_session: Session | None = field(default=None, init=False)
    last_resolved: ResolvedModel | None = field(default=None, init=False)
    runtime_config: AgentRuntimeConfig | None = field(default=None, init=False)
    approver: Callable | None = None
    checkpoints: Any = None
    todos: TodoStore = field(default_factory=TodoStore)

    def subscribe(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _on_event(self, event: Event) -> None:
        for listener in list(self._listeners):
            listener(event)

    def prepare(self) -> tuple[AgentRuntimeConfig, ResolvedModel, str]:
        ensure_home()
        ucfg = self.user_config or UserConfig.load()
        rcfg = load_runtime_config(self.options.config_name)
        self.runtime_config = rcfg
        cwd = str(Path(self.options.cwd or ".").resolve())

        resolved = resolve_model(
            provider=self.options.provider,
            model=self.options.model,
            config=ucfg,
        )
        missing = missing_credentials(resolved)
        if missing:
            raise RuntimeError(missing)
        no_model = missing_model(resolved)
        if no_model:
            raise RuntimeError(no_model)
        self.last_resolved = resolved

        skills = load_skills(cwd, extra_dirs=rcfg.skills.dirs) if rcfg.skills.enabled else []

        project_ctx = None
        if not self.options.no_context:
            project_ctx = gather_project_context(
                cwd,
                include_git=rcfg.context.include_git_status and ucfg.include_git_status,
                include_tree=rcfg.context.include_tree_snippet and ucfg.include_tree_snippet,
                tree_max_entries=rcfg.context.tree_max_entries,
            )

        extra_sections: list[str] = []
        mode = (self.options.mode or "build").lower()
        try:
            extra_sections.append(load_prompt_template(f"mode_{mode}"))
        except (FileNotFoundError, OSError):
            pass

        memory_text = MemoryStore.open(cwd).render_for_prompt()

        system = assemble_system_prompt(
            config=rcfg,
            project_context=project_ctx,
            skills=skills,
            extra_sections=extra_sections,
            override_system=self.options.system_prompt_override,
            memory=memory_text,
        )
        return rcfg, resolved, system

    def run(self, task: str) -> dict:
        ucfg = self.user_config or UserConfig.load()
        rcfg, resolved, system = self.prepare()
        cwd = str(Path(self.options.cwd or ".").resolve())

        # Expand /skill, /commit, custom commands, plugin commands
        skills = load_skills(cwd, extra_dirs=rcfg.skills.dirs) if rcfg.skills.enabled else []
        task = expand_prompt_slash(task, cwd, extra_skill_dirs=rcfg.skills.dirs)
        mem = MemoryStore.open(cwd)

        guard = None
        if rcfg.guardrails.enabled and not self.options.no_guardrails:
            guard = GuardrailPolicy(rcfg.guardrails, cwd)

        try:
            mode = AgentMode(self.options.mode or "build")
        except ValueError:
            mode = AgentMode.BUILD
        try:
            approval = ApprovalMode(self.options.approval or "auto")
        except ValueError:
            approval = ApprovalMode.AUTO

        enabled = tools_for_mode(mode, list(rcfg.tools.enabled))
        tools = make_coding_tools(
            cwd=cwd,
            timeout=rcfg.tools.bash_timeout_seconds,
            enabled=enabled,
            guardrails=guard,
            skills=skills,
            todos=self.todos,
            memory=mem,
        )
        registry = ToolRegistry(tools)
        env = LocalEnvironment(cwd=cwd, registry=registry)
        model = LitellmModel(resolved=resolved, registry=registry, on_event=self._on_event)

        session: Session | None = None
        resume_messages: list[dict] | None = None
        if self.options.session_id or self.options.resume:
            sid = self.options.session_id
            if not sid:
                raise RuntimeError("resume requires session id")
            session = load_session(sid)
            resume_messages = list(session.messages)
            while resume_messages and resume_messages[-1].get("role") == "exit":
                resume_messages.pop()
            self.last_session = session
        else:
            session = create_session(
                task=task[:500],
                cwd=cwd,
                provider=resolved.provider,
                model=resolved.model,
                label=self.options.label,
            )
            self.last_session = session

        out_path = self.options.output_path
        if out_path is None and session is not None:
            out_path = ensure_home() / "trajectories" / f"{session.id}.json"

        instance = assemble_instance_prompt(config=rcfg, task="{task}")

        agent = DefaultAgent(
            model,
            env,
            system_prompt=system,
            instance_prompt=instance,
            project_context="",  # already folded into system by assemble_system_prompt
            step_limit=self.options.step_limit if self.options.step_limit is not None else rcfg.step_limit,
            cost_limit=self.options.cost_limit if self.options.cost_limit is not None else rcfg.cost_limit,
            wall_time_limit_seconds=(
                self.options.wall_time_limit_seconds
                if self.options.wall_time_limit_seconds is not None
                else rcfg.wall_time_limit_seconds
            ),
            max_consecutive_format_errors=rcfg.max_consecutive_format_errors,
            output_path=out_path,
            on_event=self._on_event,
            session=session,
            resume_messages=resume_messages,
            context_window=resolved.context_window,
            auto_compact=rcfg.auto_compact and ucfg.auto_compact and not self.options.no_compact,
            compaction_reserve_tokens=rcfg.compaction_reserve_tokens,
            compaction_keep_recent_tokens=rcfg.compaction_keep_recent_tokens,
            mode=mode,
            approval=approval,
            approver=self.approver,
            checkpoints=self.checkpoints,
            interactive=self.options.interactive,
            todos=self.todos,
        )

        follow = self.options.follow_up
        if resume_messages is not None:
            return agent.run(task if not follow else "", follow_up=follow or task)
        return agent.run(task)
