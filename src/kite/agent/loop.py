"""Default agent — mini control flow + context/memory hooks."""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from kite.agent.events import Event
from kite.agent.exceptions import FormatError, InterruptAgentFlow, Interrupted, LimitsExceeded, Submitted, TimeExceeded
from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.loop_guard import LoopGuard
from kite.agent.verification import VerificationCollector
from kite.memory.session import Session
from kite.agent.mode import MUTATING_TOOLS, AgentMode, ApprovalMode
from kite.prompts import load_prompt_template

try:
    SYSTEM_PROMPT = load_prompt_template("system")
except Exception:  # pragma: no cover
    SYSTEM_PROMPT = "You are a coding agent. Use tools. Submit with COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT."

try:
    INSTANCE_PROMPT = load_prompt_template("instance")
except Exception:  # pragma: no cover
    INSTANCE_PROMPT = "Please solve this task:\n\n{task}\n"


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
        self._cost_warned = False

        self.messages: list[dict] = []
        self.cost = 0.0
        self.n_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()
        self.last_usage_estimate = None
        self._compactor: LoopCompactor | None = None
        self._interrupt = False
        self._loop_guard = LoopGuard()
        self._tool_started_at: float | None = None
        if hasattr(self.model, "should_stop"):
            self.model.should_stop = lambda: self._interrupt

    def request_interrupt(self) -> None:
        self._interrupt = True
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

    def _emit(self, kind: str, **payload) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def _full_system(self) -> str:
        if not self.project_context:
            return self.system_prompt
        return f"{self.system_prompt}\n\n# Active project context\n{self.project_context}"

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
                ),
                system=self._full_system(),
                tool_schemas=schemas,
                on_event=self.on_event,
                summarizer=self.summarizer,
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
        if self.attachments:
            from kite.ui.attach import user_content_with_attachments

            if self.resume_messages:
                prompt = follow
            else:
                prompt = self.instance_prompt.format(task=task, **{k: v for k, v in kwargs.items() if k not in {"follow_up", "attachments"}})
            content = user_content_with_attachments(prompt, self.attachments, images=self.send_images)

        if self.resume_messages:
            self.messages = list(self.resume_messages)
            if follow:
                payload = content if self.attachments else follow
                self.add_messages(self.model.format_message(role="user", content=payload))
        else:
            self.messages = []
            if not self.attachments:
                content = self.instance_prompt.format(task=task, **{k: v for k, v in kwargs.items() if k not in {"follow_up", "attachments"}})
            self.add_messages(
                self.model.format_message(role="system", content=self._full_system()),
                self.model.format_message(role="user", content=content),
            )

        try:
            while True:
                try:
                    self._emit("turn_start")
                    self._maybe_compact()
                    self.step()
                    self.n_consecutive_format_errors = 0
                    self._emit("turn_end")
                except FormatError as e:
                    self.cost += e.messages[0].get("extra", {}).get("cost", 0.0) if e.messages else 0.0
                    self.n_consecutive_format_errors += 1
                    if 0 < self.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                        self.add_messages(
                            *e.messages,
                            {
                                "role": "exit",
                                "content": "RepeatedFormatError",
                                "extra": {"exit_status": "RepeatedFormatError", "submission": ""},
                            },
                        )
                    else:
                        self.add_messages(*e.messages)
                except Interrupted as e:
                    self.add_messages(*e.messages)
                    self.add_messages(
                        {
                            "role": "exit",
                            "content": "Interrupted",
                            "extra": {"exit_status": "Interrupted", "submission": ""},
                        }
                    )
                except InterruptAgentFlow as e:
                    self.add_messages(*e.messages)
                except Exception as e:
                    self.add_messages(
                        {
                            "role": "exit",
                            "content": str(e),
                            "extra": {
                                "exit_status": type(e).__name__,
                                "submission": "",
                                "traceback": traceback.format_exc(),
                            },
                        }
                    )
                    self._emit("error", error=str(e), traceback=traceback.format_exc())
                    raise

                if self.messages and self.messages[-1].get("role") == "exit":
                    break
        finally:
            self.save(self.output_path)
            vsum = self.verification.summary()
            self._emit("artifact", **vsum)
            self._flush_task_commit()

        result = self.messages[-1].get("extra", {}) if self.messages else {}
        if result:
            result = {**result, "verification": vsum, "verification_status": vsum.get("status")}
        if self.session is not None:
            self.session.set_exit(str(result.get("exit_status") or ""))
        self._emit("agent_end", **result)
        return result

    def step(self) -> list[dict]:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        if 0 < self.step_limit <= self.n_calls or 0 < self.cost_limit <= self.cost:
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "LimitsExceeded",
                    "extra": {"exit_status": "LimitsExceeded", "submission": ""},
                }
            )
        if 0 < self.wall_time_limit_seconds <= int(time.time() - self._start_time):
            raise TimeExceeded(
                {
                    "role": "exit",
                    "content": "TimeExceeded",
                    "extra": {"exit_status": "TimeExceeded", "submission": ""},
                }
            )
        self.n_calls += 1
        try:
            messages = self.messages
            if self.hooks is not None:
                messages = self.hooks.call("before_query", messages)
                self.messages = messages
            message = self.model.query(self.messages)
            if self.hooks is not None:
                message = self.hooks.call("after_query", message)
        except KeyboardInterrupt:
            self.request_interrupt()
            raise Interrupted(
                {
                    "role": "user",
                    "content": "The user interrupted generation. Wait for their next message.",
                }
            ) from None
        if self._interrupt:
            raise Interrupted(
                {
                    "role": "user",
                    "content": "The user interrupted generation. Wait for their next message.",
                }
            )
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

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        if not actions:
            content = (message.get("content") or "").strip()
            if (self.interactive or self.mode is AgentMode.PLAN) and content:
                raise Submitted(
                    {
                        "role": "exit",
                        "content": content,
                        "extra": {"exit_status": "Submitted", "submission": content},
                    }
                )
            return self.add_messages(
                {
                    "role": "user",
                    "content": (
                        "No tool calls in your last message. Use a tool, or submit via bash "
                        "with COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT."
                    ),
                }
            )
        outputs = []
        for action in actions:
            if self._interrupt:
                outputs.append({"ok": False, "error": "interrupted", "output": "interrupted", "blocked": True})
                break
            tool = str(action.get("tool") or "")
            args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            if self.hooks is not None:
                action = self.hooks.call("before_tool", action) or action
                tool = str(action.get("tool") or tool)
                args = action.get("arguments") if isinstance(action.get("arguments"), dict) else args
            self._emit("tool_start", tool=tool, arguments=args, reason=args.get("reason"))
            self._tool_started_at = time.time()

            try:
                if self.mode is AgentMode.PLAN and tool in MUTATING_TOOLS and tool != "todo_write":
                    cmd = str(args.get("command") or "").strip()
                    submit_ok = tool == "bash" and "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in cmd and "&&" not in cmd
                    if not submit_ok:
                        out = {
                            "ok": False,
                            "blocked": True,
                            "error": "blocked in plan mode — /build to apply edits",
                            "output": "blocked in plan mode — switch to build to mutate the workspace",
                        }
                    else:
                        out = self._run_gated(tool, args, action)
                else:
                    out = self._run_gated(tool, args, action)
            except Submitted:
                self._emit("tool_end", tool=tool, ok=True, preview="submitted", output="", error="")
                raise

            preview = (out.get("output") or out.get("error") or "")[:120]
            duration_ms = None
            if self._tool_started_at is not None:
                duration_ms = int((time.time() - self._tool_started_at) * 1000)
                self._tool_started_at = None
            structured = {
                "tool": tool,
                "ok": out.get("ok", True),
                "blocked": out.get("blocked", False),
                "duration_ms": duration_ms,
                "exit_code": out.get("returncode"),
                "preview": preview.replace("\n", " "),
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
                preview=preview.replace("\n", " "),
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
            if (
                out.get("ok")
                and tool in {"write", "edit"}
                and out.get("path")
            ):
                self._note_edit(str(out["path"]))
            loop_warn = self._loop_guard.record(tool, args)
            if loop_warn:
                self._emit("loop_warning", message=loop_warn, tool=tool)
                existing = str(out.get("output") or out.get("error") or "")
                out = {**out, "output": f"{loop_warn}\n\n{existing}".strip(), "loop_warning": True}
            self.verification.on_tool_end(tool, args, out)
            if self.hooks is not None:
                self.hooks.call("after_tool", out, tool=tool, args=args)
            if self.audit is not None:
                self.audit.log_tool(tool, ok=bool(out.get("ok")), duration_ms=duration_ms)
            outputs.append(out)
        obs = self.add_messages(*self.model.format_observation_messages(message, outputs))
        if self._interrupt:
            raise Interrupted(
                {
                    "role": "user",
                    "content": "The user interrupted generation. Wait for their next message.",
                }
            )
        return obs

    def _run_gated(self, tool: str, args: dict, action: dict) -> dict:
        if self.approver and tool in MUTATING_TOOLS:
            extra = {"reason": args.get("reason") or "", "diff": ""}
            if tool in {"write", "edit"}:
                extra["diff"] = self._preview_diff(tool, args)
            self._emit("approval", tool=tool, arguments=args, **extra)
            decision = self.approver(tool, args, extra)
            if decision == "stop":
                self.request_interrupt()
                return {"ok": False, "blocked": True, "error": "stopped by user", "output": "stopped by user"}
            if decision == "deny":
                return {
                    "ok": False,
                    "blocked": True,
                    "error": "denied by user",
                    "output": "denied by user",
                }
        return self.env.execute(action)

    def _preview_diff(self, tool: str, args: dict) -> str:
        path = args.get("path")
        if not path:
            return ""
        try:
            from pathlib import Path

            p = Path(path)
            if not p.is_absolute():
                cwd = getattr(self.env, "cwd", None) or "."
                p = Path(cwd) / path
            before = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        except OSError:
            return ""
        if tool == "write":
            after = str(args.get("content") or "")
        elif tool == "edit":
            old, new = str(args.get("old") or ""), str(args.get("new") or "")
            if args.get("replace_all"):
                after = before.replace(old, new)
            else:
                after = before.replace(old, new, 1)
        else:
            return ""
        from kite.tools.coding import _unified_diff

        return _unified_diff(str(path), before, after)

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
                "kite_version": "0.6.0",
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
