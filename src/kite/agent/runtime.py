"""Agent runtime — assembles config, prompts, skills, tools, guardrails, loop."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TextIO

from kite.agent.cancel import CancelToken
from kite.agent.events import Event
from kite.agent.hooks import HarnessSlots, HookBus
from kite.agent.loop import DefaultAgent
from kite.agent.mode import (
    AgentMode,
    ApprovalMode,
    parse_approval_mode,
    tools_for_mode,
    tools_for_nested_subagent,
)
from kite.agent.orchestrator import SubagentOrchestrator
from kite.agent.queue import RunMessageQueue
from kite.agent.role import AgentRole, parse_role, tools_for_role
from kite.agent.verification import VerificationCollector
from kite.cli.slash import expand_prompt_slash
from kite.config import AgentRuntimeConfig, UserConfig, ensure_home, load_runtime_config
from kite.context.discovery import gather_project_context
from kite.context.workspace import ExecutionMode, ExecutionSession, WorkspaceContext
from kite.env.local import LocalEnvironment
from kite.guardrails import GuardrailPolicy
from kite.guardrails.redact import sanitize_value
from kite.memory.audit import AuditLog
from kite.memory.session import Session, create_session, load_session
from kite.memory.store import MemoryStore
from kite.models.cache import PromptCacheManager
from kite.prompts import assemble_instance_prompt, load_prompt_template
from kite.providers.resolve import ResolvedModel, missing_credentials, missing_model, resolve_model
from kite.skills.loader import load_skills
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools
from kite.tools.jobs import JobRegistry
from kite.tools.store import TodoStore

_TRACE_FIELD_CHARS = 4096
_TRACE_TRUNCATED = "…[truncated]"


class _JsonlTrace:
    """Bounded event sink; owner-only on POSIX, best-effort permissions on Windows."""

    def __init__(self, path: str) -> None:
        from threading import Lock
        from uuid import uuid4

        self._started = time.monotonic()
        self._run_id = uuid4().hex
        self._lock = Lock()
        self._handle: TextIO | None = None
        self._warned = False
        try:
            # secure_io's atomic replacement helpers cannot append a live stream.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                if os.name == "nt":
                    # Windows lacks fchmod and chmod only controls the read-only bit.
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                else:
                    os.fchmod(fd, 0o600)
                self._handle = os.fdopen(fd, "a", encoding="utf-8", buffering=1)
            except BaseException:
                os.close(fd)
                raise
        except Exception:
            self._warn()

    def _warn(self) -> None:
        if self._warned:
            return
        self._warned = True
        try:
            # Do not echo paths or exception text that might contain a secret.
            sys.stderr.write("[kite] warning: KITE_TRACE_JSONL failed; tracing disabled for this run\n")
            sys.stderr.flush()
        except Exception:
            pass

    def __call__(self, event: Event) -> None:
        with self._lock:
            if self._handle is None:
                return
            try:
                t = time.monotonic() - self._started
                ts = time.time()
                payload = sanitize_value(event.payload)
                for key, value in payload.items():
                    if isinstance(value, (dict, list, tuple, set)):
                        preview = json.dumps(value, ensure_ascii=False, default=str)
                    elif isinstance(value, str):
                        preview = value
                    else:
                        continue
                    if len(preview) > _TRACE_FIELD_CHARS:
                        payload[key] = preview[: _TRACE_FIELD_CHARS - len(_TRACE_TRUNCATED)] + _TRACE_TRUNCATED
                # Payload fields must never override the trace's identity/timing.
                record = {"t": t, "ts": ts, "run_id": self._run_id, "type": event.kind}
                record.update((key, value) for key, value in payload.items() if key not in record)
                self._handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except Exception:
                self._warn()
                self._close()

    def _close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                self._warn()

    def close(self) -> None:
        with self._lock:
            self._close()


def _format_subagent_log_line(kind: str, payload: dict[str, Any]) -> str:
    """One human-readable ring line per crew event for /agents watch."""
    try:
        if kind == "tool_start":
            tool = str(payload.get("tool") or "?")
            args = payload.get("args")
            detail = ""
            if isinstance(args, dict):
                cmd = str(args.get("command") or args.get("path") or args.get("pattern") or "")
                detail = cmd.replace("\n", " ").strip()[:160]
            line = f"▸ {tool} {detail}".rstrip() + "\n"
            return line
        if kind == "tool_output" or kind == "job_output":
            line = str(payload.get("line") or "").rstrip("\n")
            return (line + "\n") if line else ""
        if kind == "tool_progress":
            hint = str(payload.get("hint") or "").strip()
            tool = str(payload.get("tool") or "?")
            return f"… {tool} {hint}\n".rstrip() + "\n" if hint else ""
        if kind == "tool_end":
            tool = str(payload.get("tool") or "?")
            ok = payload.get("ok", True)
            preview = str(payload.get("preview") or "")[:160].replace("\n", " ")
            mark = "✓" if ok else "✗"
            return f"{mark} {tool} {preview}\n".rstrip() + "\n"
    except Exception:
        return ""
    return ""


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
    memory_in_prompt: bool = False
    goal_objective: str = ""
    allowed_tools: list[str] | None = None  # per-worker registry allowlist (None = inherit parent)


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
    ask_user: Callable | None = None
    checkpoints: Any = None
    todos: TodoStore = field(default_factory=TodoStore)
    slots: HarnessSlots = field(default_factory=HarnessSlots)
    hooks: HookBus = field(default_factory=HookBus)
    extra_tools: list[Any] = field(default_factory=list)
    sol_pi: object | None = None
    last_agent: DefaultAgent | None = field(default=None, init=False)
    _audit_listener_attached: bool = field(default=False, init=False)
    job_registry: JobRegistry | None = None
    cancel_token: CancelToken | None = None  # inject for nested/subagent runs
    tool_executor_override: Any = None
    policy_engine_override: Any = None
    message_queue: RunMessageQueue | None = None
    _last_setup: str = field(default="", init=False)
    _static_prepare_cache: tuple[Any, ...] | None = field(default=None, init=False)
    #: Last event-listener exception, with traceback. Non-fatal by design (a
    #: frontend must never break a run) but never discarded - this is what
    #: `/trace` and a bug report read when a turn "just stops".
    last_listener_error: str = field(default="", init=False)
    _listener_errors: int = field(default=0, init=False)
    _pending_listener_error: str = field(default="", init=False)
    _trace_path: str = field(default_factory=lambda: os.environ.get("KITE_TRACE_JSONL", ""), init=False, repr=False)

    def invalidate_prepare_cache(self) -> None:
        """Drop cached project context / skills / resolve (e.g. after /reload)."""
        self._static_prepare_cache = None

    def _static_prepare_key(self, cwd: str) -> tuple[Any, ...]:
        o = self.options
        return (
            cwd,
            o.config_name,
            o.provider,
            o.model,
            o.no_context,
            o.mode,
            o.role,
            o.long_task,
            o.goal_objective,
            o.label,
        )

    def _prepare_static(
        self, ucfg: UserConfig, cwd: str
    ) -> tuple[AgentRuntimeConfig, ResolvedModel, list[Any], Any, list[str]]:
        key = self._static_prepare_key(cwd)
        if self._static_prepare_cache is not None and self._static_prepare_cache[0] == key:
            _, rcfg, resolved, skills, project_ctx, extra_sections = self._static_prepare_cache
            self.runtime_config = rcfg
            self.last_resolved = resolved
            self._prepared_skills = skills
            return rcfg, resolved, skills, project_ctx, list(extra_sections)

        rcfg = load_runtime_config(self.options.config_name)
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
        goal_text = (self.options.goal_objective or "").strip()
        if goal_text and self.options.label != "subagent":
            try:
                extra_sections.append(load_prompt_template("mode_goal"))
            except (FileNotFoundError, OSError):
                pass
            from kite.memory.goal import format_goal_section

            extra_sections.append(format_goal_section(goal_text))

        if self.options.label != "subagent":
            try:
                from kite.agent.subagent_profiles import profiles_for_orchestrator

                catalog = profiles_for_orchestrator()
                if catalog.strip():
                    extra_sections.append(catalog)
            except Exception:
                pass

        self.runtime_config = rcfg
        self.last_resolved = resolved
        self._prepared_skills = skills
        self._static_prepare_cache = (key, rcfg, resolved, skills, project_ctx, tuple(extra_sections))
        return rcfg, resolved, skills, project_ctx, extra_sections

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
            try:
                listener(event)
            except Exception:
                # A listener is a frontend (the REPL display, the audit log, the
                # job ring). One of them raising must never break the run or
                # starve the other listeners, so this stays non-fatal - but it
                # must not be invisible either: a raised display listener is
                # how "text came but the agent stopped" looked from the inside.
                # Record it on the runtime for /trace-style diagnosis, and
                # surface the first one of the turn as an event the UI can show.
                self._record_listener_failure(listener, event)

    def _record_listener_failure(
        self, listener: Callable[[Event], None], event: Event
    ) -> None:
        exc = sys.exc_info()[1]
        detail = f"{type(exc).__name__}: {exc}" if exc is not None else "unknown listener error"
        label = getattr(listener, "__qualname__", None) or type(listener).__name__
        record = (
            f"event listener {label} failed on {event.kind}: {detail}\n"
            + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
        self.last_listener_error = record
        self._listener_errors += 1
        # First failure of the turn only: a broken listener would otherwise
        # re-notify on every event for the rest of the run.
        if self._listener_errors == 1:
            self._pending_listener_error = record

    def take_listener_error(self) -> str:
        """Consume the first listener failure of the turn (empty if none).

        The runtime cannot print - it has no console, and the REPL is one of the
        listeners that may be the thing that is broken. So it parks the record
        and the frontend asks for it when the turn is over, which is the one
        moment where printing cannot race the stream.
        """
        record = self._pending_listener_error
        self._pending_listener_error = ""
        return record

    def begin_turn(self) -> None:
        """Clear per-turn listener-failure state so notices do not accumulate."""
        self._listener_errors = 0
        self._pending_listener_error = ""

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
        cwd = str(Path(self.options.cwd or ".").resolve())
        rcfg, resolved, skills, project_ctx, extra_sections = self._prepare_static(ucfg, cwd)

        memory_store = MemoryStore.open(cwd) if self.slots.memory is None else self.slots.memory
        inject_memory = rcfg.memory.inject == "always" or self.options.memory_in_prompt
        memory_text = memory_store.retrieve_for_prompt(str(self.options.follow_up or "")) if inject_memory else ""

        user_context_text = ""
        if self.options.label != "subagent" and not self.options.no_context:
            try:
                from kite.memory.user_context import render_user_context

                user_context_text = render_user_context(memory_store)
            except Exception:
                pass

        continuity_text = ""
        try:
            from kite.memory.continuity import format_continuity_section, latest_continuity_markdown

            cont = latest_continuity_markdown(
                memory_store,
                session_id=str(self.options.session_id or ""),
            )
            if cont:
                continuity_text = format_continuity_section(cont)
        except Exception:
            pass

        if self.slots.assemble_system is not None:
            slot_sections = list(extra_sections)
            if user_context_text.strip():
                slot_sections.append(user_context_text.strip())
            system = self.slots.assemble_system(
                config=rcfg,
                project_context=project_ctx,
                skills=skills,
                extra_sections=slot_sections,
                override_system=self.options.system_prompt_override,
                memory=memory_text,
                continuity=continuity_text,
                cwd=cwd,
            )
            self._last_setup = ""
        else:
            from kite.prompts import split_system_and_setup

            stable, setup = split_system_and_setup(
                config=rcfg,
                project_context=project_ctx,
                skills=skills,
                extra_sections=extra_sections,
                override_system=self.options.system_prompt_override,
                memory=memory_text,
                working_style=user_context_text,
                continuity=continuity_text,
                cwd=cwd,
            )
            system = stable
            self._last_setup = setup
        self.hooks.fire(
            "after_prepare",
            config=rcfg,
            resolved=resolved,
            system=system,
            cwd=cwd,
        )
        return rcfg, resolved, system

    def run(self, task: str) -> dict:
        """Run with an optional trace listener, including setup and teardown events."""
        if not self._trace_path:
            return self._run(task)
        trace = _JsonlTrace(self._trace_path)
        # The existing fan-out is also the trace choke point: when disabled,
        # _on_event does no extra work, not even an environment lookup/branch.
        self._listeners.insert(0, trace)
        try:
            return self._run(task)
        finally:
            self._listeners.remove(trace)
            trace.close()

    def _run(self, task: str) -> dict:
        # Fresh per-turn listener-failure budget. REPL turns share one Harness
        # (and its runtime) across runs, so without this reset _listener_errors
        # never returns to 0 and the first-failure notice stops being parked
        # after the first turn that ever saw one.
        self.begin_turn()
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
            auto_venv=rcfg.auto_venv,
        )
        execution = ExecutionSession(workspace, auto_venv=rcfg.auto_venv)

        guard = None
        if rcfg.guardrails.enabled and not self.options.no_guardrails:
            guard = GuardrailPolicy(rcfg.guardrails, cwd, execution=execution)

        try:
            mode = AgentMode(self.options.mode or "build")
        except ValueError:
            mode = AgentMode.BUILD
        approval = parse_approval_mode(self.options.approval or "auto", default=ApprovalMode.AUTO)

        enabled = tools_for_mode(mode, rcfg.tools.enabled)
        if self.options.label == "subagent":
            enabled = tools_for_nested_subagent(rcfg.tools.enabled)
        role = parse_role(self.options.role or rcfg.role, mode=mode.value)
        enabled = tools_for_role(role, enabled)

        if self.job_registry is None:
            self.job_registry = JobRegistry(on_event=self._on_event)
        else:
            self.job_registry.set_on_event(self._on_event)

        _SUBAGENT_EVENT_KINDS = frozenset(
            {"tool_start", "tool_end", "tool_output", "tool_progress", "job_output"}
        )

        def _subagent_runner(
            prompt: str,
            *,
            cancel: CancelToken | None = None,
            profile: str = "",
            role: str = "auto",
            label: str = "subagent",
            subagent_id: str = "",
            glyph: str = "◆",
            provider: str = "",
            model: str = "",
            model_role: str = "",
            allowed_tools: list[str] | None = None,
        ) -> dict:
            from kite.agent.harness import Harness
            from kite.agent.harness_build import build_harness_config
            from kite.agent.subagent_profiles import (
                ROLE_MODEL_TIERS,
                get_profile,
                resolve_worker_model,
                worker_tool_allowlist,
            )
            from kite.application.cli import execute_harness_task, legacy_result_from_run
            from kite.application.policy import child_inherits_parent_policy
            from kite.providers.resolve import resolve_model

            inherited = child_inherits_parent_policy(
                parent_approval=self.options.approval or "auto",
                parent_mode=self.options.mode or "build",
                parent_no_guardrails=bool(self.options.no_guardrails),
                parent_execution_mode=self.options.execution_mode,
                child_overrides={"mode": "plan", "approval": "readonly"},
            )
            child_role = (role or "auto").strip().lower()
            prof = get_profile(profile) if profile else None
            tier = (model_role or (prof.model_role if prof else "") or "coder").strip().lower()
            if tier not in ROLE_MODEL_TIERS:
                tier = "coder"
            child_provider = (provider or "").strip() or resolved.provider
            child_model = resolve_worker_model(
                explicit_model=(model or "").strip(),
                parent_model=resolved.model,
                model_role=tier,
            ) or resolved.model
            if provider or model:
                child_resolved = resolve_model(
                    provider=child_provider or None,
                    model=child_model or None,
                    config=ucfg,
                )
                child_provider = child_resolved.provider
                child_model = child_resolved.model
            scope = list(allowed_tools) if allowed_tools else worker_tool_allowlist(prof)
            h = Harness(
                build_harness_config(
                    cwd=cwd,
                    provider=child_provider,
                    model_name=child_model,
                    step_limit=min(rcfg.orchestrator_step_limit, rcfg.step_limit),
                    cost_limit=min(rcfg.orchestrator_cost_limit, rcfg.cost_limit),
                    approval=str(inherited["approval"]),
                    mode=str(inherited["mode"]),
                    no_guardrails=bool(inherited["no_guardrails"]),
                    execution_mode=str(inherited["execution_mode"]),
                    interactive=False,
                    no_context=True,
                    label="subagent",
                    role=child_role,
                    allowed_tools=scope,
                ),
                user_config=ucfg,
            )
            h.job_registry = self.job_registry

            def _relay(event: Event) -> None:
                if event.kind in _SUBAGENT_EVENT_KINDS and subagent_id:
                    payload = dict(event.payload)
                    payload.setdefault("subagent_id", subagent_id)
                    payload.setdefault("subagent_label", label)
                    payload.setdefault("subagent_glyph", glyph)
                    if profile:
                        payload.setdefault("subagent_profile", profile)
                    # Mirror crew activity into the job ring so
                    # /agents watch <id> shows commands even for
                    # finished workers (live stream shows running ones).
                    try:
                        _job = self.job_registry.get(subagent_id) if self.job_registry else None
                        if _job is not None:
                            _line = _format_subagent_log_line(event.kind, payload)
                            if _line:
                                _job.append_log(_line)
                    except Exception:
                        pass
                    self._on_event(Event(kind=event.kind, payload=payload))
                else:
                    self._on_event(event)

            h.subscribe(_relay)
            run_result = execute_harness_task(h, prompt, cancel=cancel)
            return legacy_result_from_run(run_result)

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
                on_event=self._on_event,
                auto_venv=rcfg.auto_venv,
                ask_user=self.ask_user,
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
        sol_pi_session = self.sol_pi
        if sol_pi_session is not None:
            from kite.sol_pi.integration import apply_sol_pi_tools

            bash_tool = next((t for t in tools if t.name == "bash"), None)
            bash_fn = bash_tool.run if bash_tool is not None else (lambda _: {"ok": False, "output": "bash unavailable"})
            tools = apply_sol_pi_tools(tools, sol_pi_session, bash_fn=bash_fn)
        if self.options.allowed_tools:
            # Per-worker least-privilege scope (Part A): restricted profiles get only their
            # allowlisted tools. Nesting/memory tools never survive into a worker registry.
            allow = set(self.options.allowed_tools) - {"subagent", "memory"}
            tools = [t for t in tools if t.name in allow]
        registry = ToolRegistry(tools)
        if self.slots.env is not None:
            env = self.slots.env(cwd=cwd, registry=registry)
        else:
            env = LocalEnvironment(cwd=cwd, registry=registry, execution=execution)

        tool_executor = self.tool_executor_override
        if tool_executor is None and self.options.use_tool_executor:
            from kite.application.execution import build_tool_executor

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
                approval=approval.value,
            )

        if self.slots.model is not None:
            model = self.slots.model(
                resolved=resolved,
                registry=registry,
                on_event=self._on_event,
                reasoning=self.options.reasoning,
            )
        else:
            from kite.models.litellm_model import LitellmModel

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

        if sol_pi_session is not None and session is not None:
            from kite.sol_pi.integration import bind_sol_pi_session

            bind_sol_pi_session(sol_pi_session, session_id=session.id, cwd=cwd)

        out_path = self.options.output_path
        if out_path is None and session is not None:
            out_path = ensure_home() / "trajectories" / f"{session.id}.json"

        instance = assemble_instance_prompt(config=rcfg, task="{task}")
        # Volatile workspace state rides in the setup user message after the
        # cache breakpoint — never in the stable system prefix (§2 Move + §4).
        setup = (getattr(self, "_last_setup", "") or "").rstrip()
        workspace_block = workspace.render_for_prompt().strip()
        if workspace_block:
            setup = "\n\n".join(p for p in (setup, workspace_block) if p).strip()
        project_setup = (setup + "\n") if setup else ""

        summarizer = self.slots.summarizer
        if summarizer is None and not self.options.no_compact:
            from kite.agent.summarize import make_summarizer

            summarizer = make_summarizer(ucfg)

        audit = AuditLog()
        verification = VerificationCollector(
            workspace_root=str(workspace.project_root),
            run_id=session.id if session else "",
        )

        from kite.config.interactive_budget import effective_agent_limits

        step_limit, cost_limit = effective_agent_limits(
            interactive=bool(self.options.interactive),
            options_step=self.options.step_limit,
            options_cost=self.options.cost_limit,
            runtime_step=rcfg.step_limit,
            runtime_cost=rcfg.cost_limit,
            user_step=ucfg.step_limit,
            user_cost=ucfg.cost_limit,
            interactive_step=getattr(rcfg, "interactive_step_limit", 80),
            interactive_cost=getattr(rcfg, "interactive_cost_limit", 10.0),
            long_task=bool(self.options.long_task),
        )

        agent = DefaultAgent(
            model,
            env,
            system_prompt=system,
            instance_prompt=instance,
            project_context=project_setup,
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
            compaction_reserve_tokens=max(rcfg.compaction_reserve_tokens, ucfg.compaction_reserve_tokens),
            compaction_keep_recent_tokens=min(
                rcfg.compaction_keep_recent_tokens,
                ucfg.compaction_keep_recent_tokens,
            ),
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
            message_queue=self.message_queue,
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
