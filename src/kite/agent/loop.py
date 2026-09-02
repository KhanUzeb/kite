"""Default agent — mini control flow + context/memory hooks."""

from __future__ import annotations

import json
import signal
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from kite.agent.events import Event
from kite.agent.exceptions import (
    FormatError,
    InterruptAgentFlow,
    Interrupted,
    LimitsExceeded,
    ProviderFault,
    Submitted,
    TimeExceeded,
)
from kite.models.retry import is_transient_provider_error, retry_delay_s
from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.loop_guard import LoopGuard
from kite.agent.verification import VerificationCollector
from kite.memory.session import Session
from kite.agent.mode import MUTATING_TOOLS, AgentMode, ApprovalMode, PARALLEL_SAFE_TOOLS
from kite.guardrails.sandbox import is_inspection_bash
from kite.prompts import load_prompt_template

try:
    from kite import __version__
except Exception:  # pragma: no cover
    __version__ = "unknown"

try:
    SYSTEM_PROMPT = load_prompt_template("system")
except Exception:  # pragma: no cover
    SYSTEM_PROMPT = "You are a coding agent. Use tools. Submit with COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT."

try:
    INSTANCE_PROMPT = load_prompt_template("instance")
except Exception:  # pragma: no cover
    INSTANCE_PROMPT = "{task}\n"


def _exit_msg(status: str, *, content: str | None = None, submission: str = "", **extra) -> dict:
    return {
        "role": "exit",
        "content": status if content is None else content,
        "extra": {"exit_status": status, "submission": submission, **extra},
    }


_MAX_IDLE_TURNS = 4
# Terse on purpose — these user nudges are re-injected into the model context.
_IDLE_NUDGE = (
    "No tool calls. Use tools or submit:\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
)
_IDLE_STALL = (
    "Stopped after {turns} idle turns (token protection). "
    "Use tools, then: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
)
_CASUAL_CHAT = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "cool",
        "bye",
        "goodbye",
        "yo",
        "sup",
        "good morning",
        "good night",
        "thx",
    }
)


def _is_casual_chat(content: str) -> bool:
    """Short greetings / thanks — may end in chat without the formal submit marker."""
    text = content.strip().lower()
    if not text or len(text) > 200:
        return False
    normalized = text.rstrip("!?. ")
    if normalized in _CASUAL_CHAT:
        return True
    if len(text) < 80 and text.endswith("?"):
        task_verbs = ("fix", "implement", "add", "create", "refactor", "debug", "build", "write", "update")
        if not any(v in text for v in task_verbs):
            return True
    return False


def _allow_text_submit(content: str, *, mode: AgentMode, interactive: bool) -> bool:
    if not content.strip():
        return False
    if mode is AgentMode.PLAN:
        return True
    if not interactive:
        return False
    return _is_casual_chat(content)
def _user_interrupt() -> Interrupted:
    return Interrupted(
        {
            "role": "user",
            "content": "The user interrupted generation. Wait for their next message.",
        }
    )


def _blocked(error: str, output: str | None = None) -> dict:
    return {"ok": False, "blocked": True, "error": error, "output": output or error}


class DefaultAgent:
    def __init__(
        self,
        model,
        env,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        instance_prompt: str = INSTANCE_PROMPT,
        project_context: str = "",
        step_limit: int = 40,
        cost_limit: float = 5.0,
        wall_time_limit_seconds: int = 0,
        max_consecutive_format_errors: int = 3,
        output_path: Path | None = None,
        on_event: Callable[[Event], None] | None = None,
        session: Session | None = None,
        resume_messages: list[dict] | None = None,
        context_window: int = 128_000,
        auto_compact: bool = True,
        compaction_reserve_tokens: int = 16_384,
        compaction_keep_recent_tokens: int = 20_000,
        compaction_ratio: float = 0.80,
        compaction_llm_ratio: float = 0.92,
        mode: AgentMode = AgentMode.BUILD,
        approval: ApprovalMode = ApprovalMode.AUTO,
        approver=None,
        checkpoints=None,
        interactive: bool = False,
        todos=None,
        hooks=None,
        summarizer=None,
        attachments=None,
        send_images: bool = True,
        verification: VerificationCollector | None = None,
        audit=None,
        tool_progress_interval_seconds: float = 5.0,
        verify_before_submit: bool = True,
        loop_hard_threshold: int = 5,
        long_task: bool = False,
        phase_checkpoint_interval: int = 10,
        provider_max_retries: int = 4,
        cancel=None,
    ):
        self.model = model
        self.env = env
        self.system_prompt = system_prompt
        self.instance_prompt = instance_prompt
        self.project_context = project_context
        self.step_limit = step_limit
        self.cost_limit = cost_limit
        self.wall_time_limit_seconds = wall_time_limit_seconds
        self.max_consecutive_format_errors = max_consecutive_format_errors
        self.output_path = output_path
        self.on_event = on_event
        self.session = session
        self.resume_messages = resume_messages
        self.context_window = context_window
        self.auto_compact = auto_compact
        self.compaction_reserve_tokens = compaction_reserve_tokens
        self.compaction_keep_recent_tokens = compaction_keep_recent_tokens
        self.compaction_ratio = compaction_ratio
        self.compaction_llm_ratio = compaction_llm_ratio
        self.mode = mode
        self.approval = approval
        self.approver = approver
        self.checkpoints = checkpoints
        self.interactive = interactive
        self.todos = todos
        self.hooks = hooks
        self.summarizer = summarizer
        self.attachments = list(attachments or [])
        self.send_images = send_images
        self._task = ""
        self.verification = verification or VerificationCollector()
        self.audit = audit
        self.tool_progress_interval_seconds = tool_progress_interval_seconds
        self.verify_before_submit = verify_before_submit
        self.long_task = long_task
        self.phase_checkpoint_interval = max(3, phase_checkpoint_interval)
        self.provider_max_retries = max(1, int(provider_max_retries))
        self.cancel = cancel
        self._cost_warned = False

        self.messages: list[dict] = []
        self.cost = 0.0
        self.n_calls = 0
        self.n_consecutive_format_errors = 0
        self._consecutive_no_tool_turns = 0
        self._start_time = time.time()
        self.last_usage_estimate = None
        self._compactor: LoopCompactor | None = None
        self._interrupt = False
        self._loop_guard = LoopGuard(hard_threshold=loop_hard_threshold)
        self._phase_markers: set[int] = set()
        self.tool_call_count = 0
        self.tool_counts: dict[str, int] = {}
        self._tool_started_at: float | None = None
        if hasattr(self.model, "should_stop"):
            self.model.should_stop = lambda: self._interrupt

    def request_interrupt(self) -> None:
        self._interrupt = True
        if self.cancel is not None:
            self.cancel.request()
        self._emit("interrupt")

    def _active_task_label(self) -> str:
        if self.todos is not None:
            for item in self.todos.read():
                if item.get("status") == "in_progress" and item.get("content"):
                    return str(item["content"])
        return self._task or "agent edits"

    def _emit_commit(self, result: dict | None) -> None:
        if not result:
            return
        sha = str(result.get("sha") or "")
        self._emit(
            "commit",
            sha=sha[:7],
            message=result.get("message") or "",
            files=result.get("files") or [],
        )

    def _flush_task_commit(self, message: str | None = None) -> None:
        if self.checkpoints is None:
            return
        self._emit_commit(self.checkpoints.flush(message=message))

    def _note_edit(self, path: str) -> None:
        if self.checkpoints is None or not path:
            return
        self._emit_commit(self.checkpoints.record(path, self._active_task_label()))

    def _maybe_phase_checkpoint(self) -> None:
        """Long-task mode: periodic checkpoints (Anthropic/OpenAI-style session persistence)."""
        if not self.long_task or self.n_calls <= 0 or self.session is None:
            return
        if self.n_calls % self.phase_checkpoint_interval != 0:
            return
        if self.n_calls in self._phase_markers:
            return
        self._phase_markers.add(self.n_calls)
        from kite.memory.context_checkpoint import save_checkpoint

        cp = save_checkpoint(
            session_id=self.session.id,
            messages=list(self.messages),
            cwd=str(getattr(self.env, "cwd", "") or ""),
            label=f"phase turn {self.n_calls}",
            reason="auto",
            todos=self.todos.read() if self.todos is not None else None,
            system=self._full_system(),
            window=self.context_window,
        )
        self.session.record_context_checkpoint(cp.id, label=cp.label, reason="auto")
        self._emit(
            "checkpoint",
            id=cp.id,
            label=cp.label,
            reason="long_task_phase",
            turn=self.n_calls,
            tokens=cp.context_usage.get("total_tokens"),
        )

    def _emit(self, kind: str, **payload) -> None:
        if self.session is not None:
            from kite.memory.session import DURABLE_EVENT_KINDS

            if kind in DURABLE_EVENT_KINDS:
                self.session.record_event(kind, payload)
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def _full_system(self) -> str:
        if not self.project_context:
            return self.system_prompt
        return f"{self.system_prompt}\n\n# Active project context\n{self.project_context}"

    def _user_turn_text(self, task: str, *, follow: str, kwargs: dict) -> str:
        """In chat, send what the user typed. One-shot `kite run` still formats through instance.md."""
        if self.resume_messages or self.interactive:
            return follow
        extra = {k: v for k, v in kwargs.items() if k not in {"follow_up", "attachments"}}
        return self.instance_prompt.format(task=task, **extra)

    def _ensure_compactor(self) -> LoopCompactor:
        if self._compactor is None:
            schemas = []
            if getattr(self.env, "registry", None) is not None:
                schemas = self.env.registry.openai_schemas()
            self._compactor = LoopCompactor(
                CompactionConfig(
                    enabled=self.auto_compact,
                    window=self.context_window,
                    reserve_tokens=self.compaction_reserve_tokens,
                    keep_recent_tokens=self.compaction_keep_recent_tokens,
                    compact_ratio=self.compaction_ratio,
                    compaction_llm_ratio=self.compaction_llm_ratio,
                ),
                system=self._full_system(),
                tool_schemas=schemas,
                on_event=self.on_event,
                summarizer=self.summarizer,
                session_id=self.session.id if self.session else None,
                cwd=str(getattr(self.env, "cwd", "") or ""),
                todos=self.todos.read() if self.todos is not None else None,
                session_meta=self.session.meta.to_dict() if self.session else None,
            )
        return self._compactor

    def add_messages(self, *messages: dict) -> list[dict]:
        self.messages.extend(messages)
        if self.session is not None:
            self.session.append(*messages)
        for m in messages:
            self._emit("message", role=m.get("role"), content=(m.get("content") or "")[:500])
        return list(messages)

    def _maybe_compact(self) -> None:
        messages = self.messages
        if self.hooks is not None:
            messages = self.hooks.call("before_compact", messages)
        result = self._ensure_compactor().maybe_compact(messages)
        self.last_usage_estimate = result.usage
        if result.compacted:
            self.messages = result.messages
            if self.session is not None:
                self.session.replace_messages(self.messages)
            if self.hooks is not None:
                self.hooks.fire("after_compact", before=result.before, after=result.after)

    def run(self, task: str = "", **kwargs) -> dict:
        self._start_time = time.time()
        self._interrupt = False
        self._task = str(kwargs.get("follow_up") or task or "")
        provider = getattr(getattr(self.model, "resolved", None), "provider", "") or ""
        model_name = getattr(getattr(self.model, "resolved", None), "model", "") or ""
        for att in self.attachments:
            self._emit("attach", name=att.name, kind=att.kind, source=att.source)
        self._emit("agent_start", task=task, provider=provider, model=model_name, mode=self.mode.value, approval=self.approval.value)
        self._emit(
            "cost_estimate",
            cost_limit=self.cost_limit,
            step_limit=self.step_limit,
            note=f"Budget: ≤${self.cost_limit:.2f} across up to {self.step_limit} model calls",
        )

        user_text = follow = kwargs.get("follow_up") or task
        content: object = user_text
        prompt = self._user_turn_text(task, follow=follow, kwargs=kwargs)
        if self.attachments:
            from kite.ui.attach import user_content_with_attachments

            content = user_content_with_attachments(prompt, self.attachments, images=self.send_images)

        if self.resume_messages:
            self.messages = list(self.resume_messages)
            if follow:
                payload = content if self.attachments else follow
                self.add_messages(self.model.format_message(role="user", content=payload))
        else:
            self.messages = []
            if not self.attachments:
                content = prompt
            self.add_messages(
                self.model.format_message(role="system", content=self._full_system()),
                self.model.format_message(role="user", content=content),
            )

        old_sigint = signal.getsignal(signal.SIGINT)
        provider_fault: str | None = None
        run_error: str | None = None
        run_traceback: str | None = None
        try:
            def _on_sigint(signum, frame):
                self.request_interrupt()

            signal.signal(signal.SIGINT, _on_sigint)
            while True:
                try:
                    self._emit("turn_start")
                    self._maybe_compact()
                    self.step()
                    self.n_consecutive_format_errors = 0
                    self._emit("turn_end")
                    self._maybe_phase_checkpoint()
                except FormatError as e:
                    self.cost += e.messages[0].get("extra", {}).get("cost", 0.0) if e.messages else 0.0
                    self.n_consecutive_format_errors += 1
                    if 0 < self.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                        self.add_messages(*e.messages, _exit_msg("RepeatedFormatError"))
                    else:
                        self.add_messages(*e.messages)
                except Interrupted as e:
                    self.add_messages(*e.messages, _exit_msg("Interrupted"))
                except InterruptAgentFlow as e:
                    self.add_messages(*e.messages)
                except ProviderFault as e:
                    provider_fault = e.error
                    if self.session is not None:
                        self.session.replace_messages(self.messages)
                    self._emit(
                        "provider_fault",
                        error=e.error,
                        attempts=e.attempts,
                        recoverable=True,
                    )
                    break
                except Exception as e:
                    run_traceback = traceback.format_exc()
                    run_error = str(e) or type(e).__name__
                    if self.session is not None:
                        self.session.replace_messages(self.messages)
                    self._emit("error", error=run_error, traceback=run_traceback)
                    break

                if self.messages and self.messages[-1].get("role") == "exit":
                    break
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            self.save(self.output_path)
            vsum = self.verification.summary()
            self._emit("artifact", **vsum)
            self._flush_task_commit()

        result = self.messages[-1].get("extra", {}) if self.messages else {}
        if provider_fault:
            result = {
                **(result or {}),
                "exit_status": "ProviderFault",
                "error": provider_fault,
                "recoverable": True,
                "cost": self.cost,
            }
        elif run_error:
            result = {
                **(result or {}),
                "exit_status": "Error",
                "error": run_error,
                "traceback": run_traceback or "",
                "cost": self.cost,
            }
        elif result:
            result = {**result, "verification": vsum, "verification_status": vsum.get("status")}
        if self.session is not None:
            self.session.set_exit(str(result.get("exit_status") or ""))
        self._emit("agent_end", **result)
        return result

    def step(self) -> list[dict]:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        if 0 < self.step_limit <= self.n_calls or 0 < self.cost_limit <= self.cost:
            raise LimitsExceeded(_exit_msg("LimitsExceeded"))
        if 0 < self.wall_time_limit_seconds <= int(time.time() - self._start_time):
            raise TimeExceeded(_exit_msg("TimeExceeded"))
        self.n_calls += 1
        last_error: BaseException | None = None
        attempts = 0
        try:
            messages = self.messages
            if self.hooks is not None:
                messages = self.hooks.call("before_query", messages)
                self.messages = messages
            while attempts < self.provider_max_retries:
                attempts += 1
                try:
                    message = self.model.query(self.messages)
                    if self.hooks is not None:
                        message = self.hooks.call("after_query", message)
                    last_error = None
                    break
                except KeyboardInterrupt:
                    self.request_interrupt()
                    raise _user_interrupt() from None
                except Exception as e:
                    last_error = e
                    if attempts >= self.provider_max_retries or not is_transient_provider_error(e):
                        raise
                    delay = retry_delay_s(attempts)
                    self._emit(
                        "provider_retry",
                        attempt=attempts,
                        max_attempts=self.provider_max_retries,
                        delay_s=delay,
                        error=str(e)[:240],
                    )
                    time.sleep(delay)
            if last_error is not None:
                raise last_error
        except KeyboardInterrupt:
            self.request_interrupt()
            raise _user_interrupt() from None
        except Exception as e:
            if is_transient_provider_error(e):
                raise ProviderFault(str(e), attempts=attempts) from e
            raise
        if self._interrupt:
            raise _user_interrupt()
        self.cost += message.get("extra", {}).get("cost", 0.0)
        self._emit("cost", cost=self.cost)
        if (
            not self._cost_warned
            and self.cost_limit > 0
            and self.cost >= 0.8 * self.cost_limit
        ):
            self._cost_warned = True
            self._emit(
                "cost_warning",
                cost=self.cost,
                limit=self.cost_limit,
                message=f"Cost at ${self.cost:.3f} — 80% of ${self.cost_limit:.2f} limit",
            )
        self.add_messages(message)
        return message

    def _handle_no_actions(self, message: dict) -> list[dict]:
        content = (message.get("content") or "").strip()
        if _allow_text_submit(content, mode=self.mode, interactive=self.interactive):
            if self.mode is AgentMode.BUILD and self.verification.has_edits():
                reason = self.verification.submit_block_reason(
                    content,
                    require_verification=self.verify_before_submit,
                )
                if reason:
                    return self.add_messages({"role": "user", "content": reason})
            raise Submitted(_exit_msg("Submitted", content=content, submission=content))
        self._consecutive_no_tool_turns += 1
        if self.mode is AgentMode.BUILD and self._consecutive_no_tool_turns >= _MAX_IDLE_TURNS:
            msg = _IDLE_STALL.format(turns=self._consecutive_no_tool_turns)
            self.add_messages(_exit_msg("Stalled", content=msg))
            return []
        return self.add_messages({"role": "user", "content": _IDLE_NUDGE})

    def _execute_parallel_actions(self, actions: list[dict], outputs: list[dict]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        prepared: list[tuple[str, dict, dict]] = []
        for action in actions:
            if self._interrupt:
                break
            prepared.append(self._prepare_action(action))
        for idx, (tool, args, _action) in enumerate(prepared, start=1):
            self._emit(
                "tool_start",
                tool=tool,
                arguments=args,
                reason=args.get("reason"),
                parallel_batch=len(prepared),
                parallel_index=idx,
            )
        started = time.time()

        def _worker(item: tuple[int, tuple[str, dict, dict]]) -> tuple[int, str, dict, dict, dict]:
            idx, (tool, args, action) = item
            return idx, tool, args, action, self._invoke_tool(tool, args, action)

        results: dict[int, tuple[str, dict, dict, dict]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(prepared))) as pool:
            for row in pool.map(_worker, list(enumerate(prepared))):
                idx, tool, args, action, out = row
                results[idx] = (tool, args, action, out)
        for idx in range(len(prepared)):
            if idx not in results:
                continue
            tool, args, action, out = results[idx]
            duration_ms = int((time.time() - started) * 1000)
            self._after_tool(tool, args, action, out, duration_ms, outputs)

    def _execute_sequential_actions(self, actions: list[dict], outputs: list[dict]) -> None:
        for action in actions:
            if self._interrupt:
                outputs.append({"ok": False, "error": "interrupted", "output": "interrupted", "blocked": True})
                break
            tool, args, action = self._prepare_action(action)
            self._emit("tool_start", tool=tool, arguments=args, reason=args.get("reason"))
            self._tool_started_at = time.time()
            try:
                out = self._invoke_tool(tool, args, action)
            except Submitted:
                self._emit("tool_end", tool=tool, ok=True, preview="submitted", output="", error="")
                raise
            duration_ms = None
            if self._tool_started_at is not None:
                duration_ms = int((time.time() - self._tool_started_at) * 1000)
                self._tool_started_at = None
            self._after_tool(tool, args, action, out, duration_ms, outputs)

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        if not actions:
            return self._handle_no_actions(message)
        self._consecutive_no_tool_turns = 0
        outputs: list[dict] = []
        parallel = len(actions) > 1 and all(
            str(a.get("tool") or "") in PARALLEL_SAFE_TOOLS for a in actions
        )
        if parallel:
            self._execute_parallel_actions(actions, outputs)
        else:
            self._execute_sequential_actions(actions, outputs)
        obs = self.add_messages(*self.model.format_observation_messages(message, outputs))
        if self._interrupt:
            raise _user_interrupt()
        return obs

    def _prepare_action(self, action: dict) -> tuple[str, dict, dict]:
        tool = str(action.get("tool") or "")
        args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        if self.hooks is not None:
            action = self.hooks.call("before_tool", action) or action
            tool = str(action.get("tool") or tool)
            args = action.get("arguments") if isinstance(action.get("arguments"), dict) else args
        return tool, args, action

    def _invoke_tool(self, tool: str, args: dict, action: dict) -> dict:
        cmd = str(args.get("command") or "").strip()
        submit_ok = (
            tool == "bash"
            and "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in cmd
            and "&&" not in cmd
        )
        plan_block = (
            self.mode is AgentMode.PLAN
            and tool in MUTATING_TOOLS
            and tool != "todo_write"
            and not submit_ok
            and not (tool == "bash" and is_inspection_bash(cmd))
        )
        if plan_block:
            return _blocked(
                "blocked in plan mode — /build to apply edits",
                "blocked in plan mode — switch to build to mutate the workspace",
            )
        try:
            return self._run_gated(tool, args, action)
        except Submitted as submitted:
            submission = ""
            if submitted.messages:
                extra = submitted.messages[0].get("extra") or {}
                submission = str(extra.get("submission") or submitted.messages[0].get("content") or "")
            reason = self.verification.submit_block_reason(
                submission,
                require_verification=self.verify_before_submit,
            )
            if reason:
                self._emit(
                    "submit_blocked",
                    reason=reason,
                    verification=self.verification.summary(),
                )
                return _blocked(
                    reason,
                    output=(
                        f"{reason}\n\n"
                        f"Verification status: {self.verification.status()}\n"
                        + "\n".join(self.verification.render_lines())
                    ),
                )
            raise

    def _after_tool(
        self,
        tool: str,
        args: dict,
        action: dict,
        out: dict,
        duration_ms: int | None,
        outputs: list[dict],
    ) -> None:
        preview = (out.get("output") or out.get("error") or "")[:120]
        flat = preview.replace("\n", " ")
        summary = str(out.get("summary") or flat)
        structured = {
            "tool": tool,
            "ok": out.get("ok", True),
            "blocked": out.get("blocked", False),
            "duration_ms": duration_ms,
            "exit_code": out.get("returncode"),
            "preview": flat,
        }
        if tool == "bash":
            structured["command"] = str(args.get("command") or "")
        elif tool in {"read", "write", "edit", "grep", "glob", "ls"}:
            structured["target"] = str(args.get("path") or args.get("pattern") or args.get("command") or "")
        elif tool in {"websearch", "webfetch", "webcrawl"}:
            structured["target"] = str(args.get("query") or args.get("url") or "")
        self._emit(
            "tool_end",
            tool=tool,
            ok=out.get("ok", True),
            blocked=out.get("blocked", False),
            preview=flat,
            summary=summary,
            output=out.get("output") or "",
            error=out.get("error") or "",
            diff=out.get("diff") or "",
            path=out.get("path") or args.get("path"),
            duration_ms=duration_ms,
            structured=structured,
            secrets_redacted=out.get("secrets_redacted"),
        )
        if tool == "todo_write" and out.get("items") is not None:
            self._emit("todo", items=out["items"])
            if out.get("ok") and self.checkpoints is not None:
                items = out["items"]
                has_in_progress = any(
                    isinstance(item, dict) and item.get("status") == "in_progress"
                    for item in items
                )
                self._emit_commit(
                    self.checkpoints.flush_if_task_changed(
                        self._active_task_label(),
                        has_in_progress=has_in_progress,
                    )
                )
        if out.get("ok") and tool in {"write", "edit"} and out.get("path"):
            self._note_edit(str(out["path"]))
        loop = self._loop_guard.record(tool, args, out)
        if loop.hard_stop:
            self._emit("loop_hard_stop", message=loop.hard_stop, tool=tool)
            out = _blocked(loop.hard_stop, output=loop.hard_stop)
        elif loop.warning:
            self._emit("loop_warning", message=loop.warning, tool=tool)
            existing = str(out.get("output") or out.get("error") or "")
            out = {**out, "output": f"{loop.warning}\n\n{existing}".strip(), "loop_warning": True}
        self.verification.on_tool_end(tool, args, out)
        if out.get("blocked"):
            pass
        else:
            self.tool_call_count += 1
            self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
        nudge = self.verification.post_edit_nudge()
        if nudge and out.get("ok") and tool in {"write", "edit"}:
            existing = str(out.get("output") or "")
            out = {**out, "output": f"{existing}\n\n{nudge}".strip()}
        if self.hooks is not None:
            self.hooks.call("after_tool", out, tool=tool, args=args)
        if self.audit is not None:
            self.audit.log_tool(
                tool,
                ok=bool(out.get("ok")),
                duration_ms=duration_ms,
                session_id=self.session.id if self.session else "",
            )
        outputs.append(out)

    def _run_gated(self, tool: str, args: dict, action: dict) -> dict:
        if self.approver and tool in MUTATING_TOOLS:
            extra = {"reason": args.get("reason") or "", "diff": ""}
            if tool in {"write", "edit"}:
                extra["diff"] = self._preview_diff(tool, args)
            self._emit("approval", tool=tool, arguments=args, **extra)
            decision = self.approver(tool, args, extra)
            if decision == "stop":
                self.request_interrupt()
                return _blocked("stopped by user")
            if decision == "deny":
                return _blocked("denied by user")
        return self._execute_with_progress(tool, action)

    def _execute_with_progress(self, tool: str, action: dict) -> dict:
        result: dict[str, dict] = {}
        error: list[BaseException] = []
        done = threading.Event()

        def worker() -> None:
            try:
                result["out"] = self.env.execute(action)
            except BaseException as e:
                error.append(e)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        start = time.monotonic()
        interval = max(0.5, float(self.tool_progress_interval_seconds))
        while not done.wait(timeout=interval):
            if self._interrupt:
                if self.cancel is not None:
                    self.cancel.request()
            elapsed = int(time.monotonic() - start)
            hint = ""
            if tool == "bash":
                args = action.get("arguments") or {}
                cmd = str(args.get("command") or "").strip().splitlines()
                if cmd:
                    preview = cmd[0][:48]
                    hint = f" — {preview}{'…' if len(cmd[0]) > 48 else ''}"
            self._emit("tool_progress", tool=tool, elapsed_s=elapsed, hint=hint)
        if error:
            raise error[0]
        return result["out"]

    def _preview_diff(self, tool: str, args: dict) -> str:
        path = args.get("path")
        if not path:
            return ""
        try:
            from pathlib import Path

            from kite.ui.diff import preview_mutating_diff

            cwd = getattr(self.env, "cwd", None) or "."
            return preview_mutating_diff(tool, Path(path), args, cwd=cwd)
        except OSError:
            return ""

    def serialize(self) -> dict:
        last = self.messages[-1] if self.messages else {}
        extra = last.get("extra", {})
        usage = self.last_usage_estimate
        return {
            "info": {
                "model_stats": {"instance_cost": self.cost, "api_calls": self.n_calls},
                "exit_status": extra.get("exit_status", ""),
                "submission": extra.get("submission", ""),
                "session_id": self.session.id if self.session else "",
                "context": {
                    "window": self.context_window,
                    "estimated_tokens": usage.total_tokens if usage else None,
                    "ratio": round(usage.ratio, 3) if usage else None,
                },
                "kite_version": __version__,
                "verification": self.verification.summary(),
            },
            "messages": self.messages,
            "trajectory_format": "kite-0.3",
        }

    def save(self, path: Path | None) -> dict:
        data = self.serialize()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        return data
