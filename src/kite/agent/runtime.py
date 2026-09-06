"""Agent runtime — assembles config, prompts, skills, tools, guardrails, loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from kite.agent.cancel import CancelToken
from kite.agent.hooks import HarnessSlots, HookBus
from kite.agent.loop import DefaultAgent
from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode, parse_approval_mode, tools_for_mode
from kite.agent.role import AgentRole, parse_role, tools_for_role
from kite.cli.slash import expand_prompt_slash
from kite.config import AgentRuntimeConfig, UserConfig, ensure_home, load_runtime_config
from kite.context.discovery import gather_project_context
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.memory.session import Session, create_session, load_session
from kite.memory.store import MemoryStore
from kite.memory.audit import AuditLog
from kite.agent.verification import VerificationCollector
from kite.models.litellm_model import LitellmModel
from kite.models.cache import PromptCacheManager
from kite.agent.orchestrator import SubagentOrchestrator
from kite.prompts import assemble_instance_prompt, assemble_system_prompt, load_prompt_template
from kite.providers.resolve import ResolvedModel, missing_credentials, missing_model, resolve_model
from kite.skills.loader import load_skills
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools
from kite.tools.jobs import JobRegistry
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
    reasoning: str = "auto"
    role: str = "auto"
    attachments: list | None = None
    long_task: bool = False
    execution_mode: str | None = None  # restricted | host — overrides runtime TOML
    use_tool_executor: bool = True


@dataclass
class AgentRuntime:
    """High-level façade used by the CLI / harness."""

    options: RuntimeOptions = field(default_factory=RuntimeOptions)
    user_config: UserConfig | None = None
    _listeners: list[Callable[[Event], None]] = field(default_factory=list, init=False)
    last_session: Session | None = field(default=None, init=False)
    last_resolved: ResolvedModel | None = field(default=None, init=False)
    runtime_config: AgentRuntimeConfig | None = field(default=None, init=False)
    _prepared_skills: list[Any] = field(default_factory=list, init=False)
    approver: Callable | None = None
    checkpoints: Any = None
    todos: TodoStore = field(default_factory=TodoStore)
    slots: HarnessSlots = field(default_factory=HarnessSlots)
    hooks: HookBus = field(default_factory=HookBus)
    extra_tools: list[Any] = field(default_factory=list)
    last_agent: DefaultAgent | None = field(default=None, init=False)
    _audit_listener_attached: bool = field(default=False, init=False)
    job_registry: JobRegistry | None = None
    cancel_token: CancelToken | None = None  # inject for nested/subagent runs
    tool_executor_override: Any = None
    policy_engine_override: Any = None

    def request_interrupt(self) -> None:
        if self.last_agent is not None:
            self.last_agent.request_interrupt()
        if self.cancel_token is not None:
            self.cancel_token.request()

    def teardown_jobs(self) -> int:
        """Kill remaining background bash/subagent jobs (session or one-shot exit)."""
        if self.job_registry is None:
            return 0
        return self.job_registry.kill_all()

    def subscribe(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _on_event(self, event: Event) -> None:
        for listener in list(self._listeners):
            listener(event)

    def _persist_session_stats(self, session: Session, result: dict, *, agent: DefaultAgent | None) -> None:
        from kite.memory.session_analytics import SessionStats, save_session_stats

        cache_hits = 0
        estimated = 0
        if agent is not None:
            usage = agent.last_usage_estimate
            if usage is not None:
                estimated = usage.total_tokens
            prompt_cache = getattr(getattr(agent, "model", None), "prompt_cache", None)
            if prompt_cache is not None:
                session_stats = getattr(prompt_cache, "session", None)
                if session_stats is not None:
                    cache_hits = int(getattr(session_stats, "cache_hit_tokens", 0) or 0)
        meta = session.meta
        stats = SessionStats(
            session_id=session.id,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
            duration_s=max(0.0, meta.updated_at - meta.created_at),
            provider=meta.provider,
            model=meta.model,
            task=meta.task,
            label=meta.label,
            cwd=meta.cwd,
            exit_status=str(result.get("exit_status") or meta.exit_status),
            verification_status=str(result.get("verification_status") or ""),
            last_error=str(result.get("error") or "")[:240],
            mode=getattr(agent, "mode", None).value if agent and getattr(agent, "mode", None) else "",
            approval=getattr(agent, "approval", None).value if agent and getattr(agent, "approval", None) else "",
            tool_calls=getattr(agent, "tool_call_count", 0) if agent else 0,
            tool_counts=dict(getattr(agent, "tool_counts", {}) or {}),
            api_calls=getattr(agent, "n_calls", 0) if agent else 0,
            cost=getattr(agent, "cost", 0.0) if agent else 0.0,
            estimated_tokens=estimated,
            cache_hit_tokens=cache_hits,
            turn_count=getattr(agent, "n_calls", 0) if agent else 0,
            message_count=len(session.messages) if hasattr(session, "messages") else 0,
        )
        save_session_stats(stats)

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
        self._prepared_skills = skills

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
        role = parse_role(self.options.role or rcfg.role, mode=mode)
        try:
            extra_sections.append(load_prompt_template(f"mode_{mode}"))
        except (FileNotFoundError, OSError):
            pass
        if role is not AgentRole.AUTO:
            try:
                extra_sections.append(load_prompt_template(f"role_{role.value}"))
            except (FileNotFoundError, OSError):
                pass
        if self.options.long_task:
            try:
                extra_sections.append(load_prompt_template("mode_long"))
            except (FileNotFoundError, OSError):
                pass

        memory_text = MemoryStore.open(cwd).render_for_prompt() if self.slots.memory is None else self.slots.memory.render_for_prompt()

        if self.slots.assemble_system is not None:
            system = self.slots.assemble_system(
                config=rcfg,
                project_context=project_ctx,
                skills=skills,
                extra_sections=extra_sections,
                override_system=self.options.system_prompt_override,
                memory=memory_text,
                cwd=cwd,
            )
        else:
            system = assemble_system_prompt(
                config=rcfg,
                project_context=project_ctx,
                skills=skills,
                extra_sections=extra_sections,
                override_system=self.options.system_prompt_override,
                memory=memory_text,
                cwd=cwd,
            )
        return rcfg, resolved, system

    def run(self, task: str) -> dict:
        ucfg = self.user_config or UserConfig.load()
        rcfg, resolved, system = self.prepare()
        if self.options.execution_mode in ("restricted", "host"):
            rcfg = replace(
                rcfg,
                guardrails=replace(rcfg.guardrails, execution_mode=self.options.execution_mode),
            )
        cwd = str(Path(self.options.cwd or ".").resolve())
        attachments = list(self.options.attachments or [])
        send_images = True
        if any(getattr(item, "kind", "") == "image" for item in attachments):
            from kite.models.vision import route_vision

            route = route_vision(resolved, config=ucfg)
            if route.source == "none":
                send_images = False
                self._on_event(
                    Event(
                        "route",
                        payload={
                            "reason": "vision-missing",
                            "provider": resolved.provider,
                            "model": resolved.model,
                        },
                    )
                )
            elif route.switched:
                resolved = resolve_model(provider=route.provider, model=route.model, config=ucfg)
                miss = missing_credentials(resolved) or missing_model(resolved)
                if miss:
                    send_images = False
                    self._on_event(Event("route", payload={"reason": "vision-missing", "error": miss}))
                else:
                    self.last_resolved = resolved
                    self._on_event(
                        Event(
                            "route",
                            payload={
                                "reason": "vision",
                                "provider": resolved.provider,
                                "model": resolved.model,
                                "source": route.source,
                            },
                        )
                    )

        # Expand /skill, /commit, custom commands, plugin commands
        skills = self._prepared_skills
        task = expand_prompt_slash(task, cwd, extra_skill_dirs=rcfg.skills.dirs)
        mem = self.slots.memory or MemoryStore.open(cwd)
        self.hooks.fire("before_run", task=task, cwd=cwd)
        # Injected cancel (nested subagent) wins; otherwise fresh token per turn.
        cancel = self.cancel_token or CancelToken()

        workspace = WorkspaceContext.discover(
            cwd,
            execution_mode=ExecutionMode.HOST if rcfg.guardrails.host_access() else ExecutionMode.RESTRICTED,
        )
        execution = ExecutionSession(workspace)

        guard = None
        if rcfg.guardrails.enabled and not self.options.no_guardrails:
            guard = GuardrailPolicy(rcfg.guardrails, cwd, execution=execution)

        try:
            mode = AgentMode(self.options.mode or "build")
        except ValueError:
            mode = AgentMode.BUILD
        approval = parse_approval_mode(self.options.approval or "auto", default=ApprovalMode.AUTO)

        enabled = tools_for_mode(mode, rcfg.tools.enabled)
        role = parse_role(self.options.role or rcfg.role, mode=mode.value)
        enabled = tools_for_role(role, enabled)

        if self.job_registry is None:
            self.job_registry = JobRegistry(on_event=self._on_event)
        else:
            self.job_registry.set_on_event(self._on_event)

        def _subagent_runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
            from kite.agent.harness import Harness, HarnessConfig
            from kite.application.policy import child_inherits_parent_policy

            inherited = child_inherits_parent_policy(
                parent_approval=self.options.approval or "auto",
                parent_mode=self.options.mode or "build",
                parent_no_guardrails=bool(self.options.no_guardrails),
                parent_execution_mode=self.options.execution_mode,
            )
            h = Harness(
                HarnessConfig(
                    cwd=cwd,
                    provider=resolved.provider,
                    model_name=resolved.model,
                    step_limit=min(rcfg.orchestrator_step_limit, rcfg.step_limit),
                    cost_limit=min(rcfg.orchestrator_cost_limit, rcfg.cost_limit),
                    approval=str(inherited["approval"]),
                    mode=str(inherited["mode"]),
                    no_guardrails=bool(inherited["no_guardrails"]),
                    execution_mode=str(inherited["execution_mode"]),
                    interactive=False,
                    no_context=True,
                    label="subagent",
                ),
                user_config=ucfg,
            )
            h.job_registry = self.job_registry
            h.subscribe(self._on_event)
            return h.run(prompt, cancel=cancel)

        orchestrator = SubagentOrchestrator(
            runner=_subagent_runner,
            on_event=self._on_event,
            max_workers=rcfg.orchestrator_max_workers,
            timeout_seconds=rcfg.orchestrator_timeout_seconds,
            jobs=self.job_registry,
        )

        if self.slots.tools is not None:
            tools = self.slots.tools(
                cwd=cwd,
                timeout=rcfg.tools.bash_timeout_seconds,
                enabled=enabled,
                guardrails=guard,
                skills=skills,
                todos=self.todos,
                memory=mem,
            )
        else:
            tools = make_coding_tools(
                cwd=cwd,
                timeout=rcfg.tools.bash_timeout_seconds,
                enabled=enabled,
                guardrails=guard,
                skills=skills,
                todos=self.todos,
                memory=mem,
                orchestrator=orchestrator,
                execution=execution,
                cancel=cancel,
                jobs=self.job_registry,
            )
        extras = list(self.extra_tools)
        if rcfg.github_tools:
            from kite.tools.github import make_github_tools

            extras.extend(make_github_tools())
        if rcfg.context7_enabled:
            from kite.tools.context7 import make_context7_tools

            extras.extend(make_context7_tools())
        if extras:
            tools = [*tools, *extras]
        registry = ToolRegistry(tools)
        if self.slots.env is not None:
            env = self.slots.env(cwd=cwd, registry=registry)
        else:
            env = LocalEnvironment(cwd=cwd, registry=registry)

        tool_executor = self.tool_executor_override
        if tool_executor is None and self.options.use_tool_executor:
            from kite.application.execution import build_tool_executor
            from kite.application.tools.contracts import ToolCall

            exec_mode = "host" if rcfg.guardrails.host_access() else "restricted"
            no_gr = bool(self.options.no_guardrails or not rcfg.guardrails.enabled)
            tool_executor = build_tool_executor(
                workspace_root=workspace.project_root,
                execution_mode=exec_mode,
                no_guardrails=no_gr,
                runner=lambda call: env.execute(
                    {"tool": call.name, "arguments": dict(call.arguments)}
                ),
                policy_engine=self.policy_engine_override,
            )

        if self.slots.model is not None:
            model = self.slots.model(
                resolved=resolved,
                registry=registry,
                on_event=self._on_event,
                reasoning=self.options.reasoning,
            )
        else:
            prompt_cache = PromptCacheManager(resolved.provider, enabled=rcfg.prompt_cache_enabled)
            model = LitellmModel(
                resolved=resolved,
                registry=registry,
                on_event=self._on_event,
                reasoning=self.options.reasoning,
                prompt_cache=prompt_cache,
                timeout_seconds=rcfg.model_timeout_seconds,
                observation_max_chars=rcfg.observation_max_chars,
            )

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
        system = system.rstrip() + "\n\n" + workspace.render_for_prompt() + "\n"

        summarizer = self.slots.summarizer
        if summarizer is None and not self.options.no_compact:
            from kite.agent.summarize import make_summarizer

            summarizer = make_summarizer(ucfg)

        audit = AuditLog()
        verification = VerificationCollector(
            workspace_root=str(workspace.project_root),
            run_id=session.id if session else "",
        )

        step_limit = self.options.step_limit if self.options.step_limit is not None else rcfg.step_limit
        cost_limit = self.options.cost_limit if self.options.cost_limit is not None else rcfg.cost_limit
        if self.options.long_task:
            if self.options.step_limit is None:
                step_limit = max(step_limit, 120)
            if self.options.cost_limit is None:
                cost_limit = max(cost_limit, 25.0)

        agent = DefaultAgent(
            model,
            env,
            system_prompt=system,
            instance_prompt=instance,
            project_context="",
            step_limit=step_limit,
            cost_limit=cost_limit,
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
            compaction_ratio=rcfg.compaction_ratio,
            compaction_llm_ratio=rcfg.compaction_llm_ratio,
            mode=mode,
            approval=approval,
            approver=self.approver,
            checkpoints=self.checkpoints,
            interactive=self.options.interactive,
            todos=self.todos,
            hooks=self.hooks,
            summarizer=summarizer,
            attachments=attachments,
            send_images=send_images,
            verification=verification,
            audit=audit,
            tool_executor=tool_executor,
            tool_progress_interval_seconds=rcfg.tools.progress_interval_seconds,
            verify_before_submit=rcfg.verify_before_submit,
            loop_hard_threshold=rcfg.loop_hard_threshold,
            provider_max_retries=rcfg.provider_max_retries,
            long_task=self.options.long_task,
            cancel=cancel,
        )
        self.last_agent = agent

        if not self._audit_listener_attached:

            def _audit_listener(event: Event) -> None:
                if event.kind == "approval":
                    p = event.payload
                    audit.log_approval(
                        str(p.get("tool") or ""),
                        str(p.get("pattern") or ""),
                        str(p.get("decision") or ""),
                    )

            self._listeners.append(_audit_listener)
            self._audit_listener_attached = True

        follow = self.options.follow_up
        if resume_messages is not None:
            result = agent.run(task if not follow else "", follow_up=follow or task)
        else:
            result = agent.run(task)
        if session is not None:
            verification_summary = verification.summary()
            audit.log_run(
                session.id,
                str(result.get("exit_status") or ""),
                verification=verification_summary,
                api_calls=getattr(self.last_agent, "n_calls", 0),
                cost=getattr(self.last_agent, "cost", 0.0),
                tool_calls=getattr(self.last_agent, "tool_call_count", 0),
            )
            self._persist_session_stats(session, result, agent=self.last_agent)
        self.hooks.fire("after_run", result=result, task=task)
        return result
