"""Headless task runs — structured stderr logging without a TTY."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode, parse_approval_mode
from kite.util.tty import is_interactive_tty

# Non-success exits that must end with a continuity brief + resume hint,
# never a bare status line (long tasks stall silently otherwise).
_LIMIT_BRIEF_EXITS = frozenset(
    {
        "LimitsExceeded",
        "TimeExceeded",
        "Stalled",
        "ProviderFault",
        "Interrupted",
        "Error",
        "RepeatedFormatError",
    }
)


def is_headless_run(*, headless_flag: bool = False, quiet: bool = False) -> bool:
    """True when we should avoid TTY prompts and use line-oriented logging."""
    if headless_flag:
        return True
    if quiet:
        return True
    return not is_interactive_tty(require_stdout=False)


@dataclass(frozen=True, slots=True)
class HeadlessTask:
    task: str
    label: str = ""
    cwd: str = ""
    mode: str = "build"
    approval: str = "auto"
    role: str = "auto"
    long_task: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], *, default_cwd: str = "") -> HeadlessTask:
        task = str(raw.get("task") or raw.get("prompt") or raw.get("message") or "").strip()
        if not task:
            raise ValueError("task field required")
        label = str(raw.get("label") or raw.get("name") or "")[:80]
        cwd = str(raw.get("cwd") or raw.get("workspace") or default_cwd or "").strip()
        return cls(
            task=task,
            label=label,
            cwd=cwd,
            mode=str(raw.get("mode") or "build").lower(),
            approval=str(raw.get("approval") or "auto").lower(),
            role=str(raw.get("role") or "auto").lower(),
            long_task=bool(raw.get("long") or raw.get("long_task")),
        )


def parse_task_line(line: str, *, default_cwd: str = "") -> HeadlessTask | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("{") and text.endswith("}"):
        try:
            row = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON task line: {e}") from e
        if not isinstance(row, dict):
            raise ValueError("JSON task line must be an object")
        return HeadlessTask.from_mapping(row, default_cwd=default_cwd)
    return HeadlessTask(task=text, cwd=default_cwd)


def load_tasks_file(path: Path, *, default_cwd: str = "") -> list[HeadlessTask]:
    tasks: list[HeadlessTask] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            task = parse_task_line(line, default_cwd=default_cwd)
        except ValueError as e:
            raise ValueError(f"{path}:{lineno}: {e}") from e
        if task is not None:
            tasks.append(task)
    if not tasks:
        raise ValueError(f"no tasks in {path}")
    return tasks


def load_tasks_text(text: str, *, default_cwd: str = "") -> list[HeadlessTask]:
    tasks: list[HeadlessTask] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        try:
            task = parse_task_line(line, default_cwd=default_cwd)
        except ValueError as e:
            raise ValueError(f"line {lineno}: {e}") from e
        if task is not None:
            tasks.append(task)
    if not tasks:
        raise ValueError("no tasks in input")
    return tasks


def _log(line: str) -> None:
    try:
        sys.stderr.write(line.rstrip("\n") + "\n")
        sys.stderr.flush()
    except OSError:
        pass


class HeadlessRunDisplay:
    """Minimal event sink for CI, cloud agents, and batch task files."""

    def __init__(self, *, stream_tools: bool = True, verbose: bool = False) -> None:
        self.stream_tools = stream_tools
        self.verbose = verbose
        self._t0 = time.monotonic()
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "agent_start": self._on_agent_start,
            "agent_end": self._on_agent_end,
            "turn_end": self._on_turn_end,
            "tool_start": self._on_tool_start,
            "tool_progress": self._on_tool_progress,
            "tool_end": self._on_tool_end,
            "tool_output": self._on_tool_output,
            "job_start": self._on_job_start,
            "job_end": self._on_job_end,
            "job_output": self._on_job_output,
            "approval": self._on_approval,
            "checkpoint": self._on_checkpoint,
            "compact": self._on_compact,
            "compaction_start": self._on_compaction_start,
            "compaction_end": self._on_compaction_end,
            "context": self._on_context,
            "limits": self._on_limits,
            "cost_warning": self._on_cost_warning,
            "provider_retry": self._on_provider_retry,
            "provider_fault": self._on_provider_fault,
            "subagent_start": self._on_subagent_start,
            "subagent_end": self._on_subagent_end,
            "orchestrator_start": self._on_orchestrator_start,
            "orchestrator_end": self._on_orchestrator_end,
            "error": self._on_error,
            "stream_delta": self._on_stream_delta,
            "stream_reasoning": self._on_stream_reasoning,
            "stream_first_token": self._on_stream_first_token,
            "stream_usage": self._on_stream_usage,
        }

    def __call__(self, event: Event) -> None:
        handler = self._handlers.get(event.kind)
        if handler is not None:
            handler(dict(event.payload))

    def _prefix(self, p: dict[str, Any]) -> str:
        glyph = str(p.get("subagent_glyph") or "")
        label = str(p.get("subagent_label") or p.get("subagent_id") or "")
        if label or glyph:
            return f"{glyph} {label}".strip() + " "
        return ""

    def _elapsed(self) -> int:
        return int(time.monotonic() - self._t0)

    def _on_agent_start(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or "").strip()
        suffix = f"  {label}" if label else ""
        _log(f"[kite] start{suffix}")

    def _on_agent_end(self, p: dict[str, Any]) -> None:
        status = str(p.get("exit_status") or p.get("status") or "done")
        _log(f"[kite] end  {status}  +{self._elapsed()}s")

    def _on_turn_end(self, p: dict[str, Any]) -> None:
        tools = p.get("tools", "?")
        dur = p.get("duration_ms", "?")
        _log(f"[kite] turn  tools={tools} {dur}ms  run +{self._elapsed()}s")

    def _on_tool_start(self, p: dict[str, Any]) -> None:
        tool = str(p.get("tool") or "?")
        args = p.get("arguments") if isinstance(p.get("arguments"), dict) else {}
        detail = ""
        if tool == "bash" and isinstance(args, dict) and args.get("command"):
            detail = str(args["command"]).replace("\n", " ").strip()[:200]
        elif isinstance(args, dict):
            for key in ("path", "pattern", "prompt", "profile"):
                if args.get(key):
                    detail = str(args[key]).replace("\n", " ")[:120]
                    break
        prefix = self._prefix(p)
        _log(f"[tool] {prefix}{tool}" + (f"  {detail}" if detail else ""))

    def _on_tool_end(self, p: dict[str, Any]) -> None:
        tool = str(p.get("tool") or "?")
        ok = p.get("ok", True)
        mark = "ok" if ok else "fail"
        prefix = self._prefix(p)
        meta = str(p.get("summary") or p.get("preview") or "")[:120]
        tail = f"  {meta}" if meta else ""
        _log(f"[tool] {prefix}{tool}  {mark}{tail}")

    def _on_tool_progress(self, p: dict[str, Any]) -> None:
        tool = str(p.get("tool") or "?")
        elapsed = p.get("elapsed_s", "?")
        hint = str(p.get("hint") or "")
        _log(f"[progress] {tool}  {elapsed}s (run +{self._elapsed()}s){hint}")

    def _on_checkpoint(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or p.get("id") or "checkpoint")
        reason = str(p.get("reason") or "")
        tokens = p.get("tokens")
        suffix = f"  {tokens} tokens" if tokens else ""
        _log(f"[kite] checkpoint  {label}  reason={reason}{suffix}")

    def _on_compact(self, p: dict[str, Any]) -> None:
        _log(f"[kite] compact  {p.get('before')}->{p.get('after')}  ratio={p.get('ratio', '?')}")

    def _on_compaction_start(self, p: dict[str, Any]) -> None:
        _log(f"[kite] compacting context  {p.get('total_tokens', '?')} tokens")

    def _on_compaction_end(self, p: dict[str, Any]) -> None:
        if p.get("compacted"):
            _log(f"[kite] compacted  {p.get('before')}->{p.get('after')}")
        else:
            _log("[kite] compaction skipped")

    def _on_context(self, p: dict[str, Any]) -> None:
        total = p.get("total_tokens", "?")
        window = p.get("window", "?")
        ratio = p.get("ratio", "?")
        _log(f"[kite] context  {total}/{window} ({ratio})  +{self._elapsed()}s")

    def _on_limits(self, p: dict[str, Any]) -> None:
        detail = p.get("detail") or p.get("message") or "budget exceeded"
        _log(f"[kite] limits  {detail}")

    def _on_cost_warning(self, p: dict[str, Any]) -> None:
        _log(f"[kite] cost  {p.get('message') or p.get('cost')}")

    def _on_approval(self, p: dict[str, Any]) -> None:
        tool = str(p.get("tool") or "?")
        args = p.get("arguments") if isinstance(p.get("arguments"), dict) else {}
        target = str(args.get("path") or args.get("command") or "")[:120]
        _log(f"[approval] {tool}" + (f"  {target}" if target else ""))

    def _on_provider_retry(self, p: dict[str, Any]) -> None:
        _log(f"[kite] provider retry  attempt {p.get('attempt')}/{p.get('max_attempts')}")

    def _on_provider_fault(self, p: dict[str, Any]) -> None:
        _log(f"[kite] provider fault  {str(p.get('error') or '')[:200]}")

    def _on_job_start(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or p.get("command") or p.get("id") or "job")
        _log(f"[job] start  {label[:120]}")

    def _on_job_end(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or p.get("id") or "job")
        status = str(p.get("status") or ("ok" if p.get("ok") else "fail"))
        elapsed = p.get("elapsed_s")
        suffix = f"  {elapsed}s" if elapsed is not None else ""
        _log(f"[job] end  {label[:120]}  {status}{suffix}")

    def _on_tool_output(self, p: dict[str, Any]) -> None:
        if not self.stream_tools:
            return
        from kite.env.shell import sanitize_shell_line
        from kite.guardrails.redact import redact_string

        line = redact_string(sanitize_shell_line(str(p.get("line") or "")))
        if line:
            _log(f"[out] {self._prefix(p)}{line.rstrip()}")

    def _on_job_output(self, p: dict[str, Any]) -> None:
        self._on_tool_output(p)

    def _on_subagent_start(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or p.get("id") or "subagent")
        profile = str(p.get("profile") or "")
        suffix = f"  profile={profile}" if profile else ""
        _log(f"[crew] start  {label}{suffix}")

    def _on_subagent_end(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or p.get("id") or "subagent")
        quality = str(p.get("quality") or ("ok" if p.get("ok") else "fail"))
        _log(f"[crew] end  {label}  {quality}")

    def _on_orchestrator_start(self, p: dict[str, Any]) -> None:
        total = int(p.get("total") or 0)
        if total > 1:
            _log(f"[crew] dispatch  {total} workers")

    def _on_orchestrator_end(self, p: dict[str, Any]) -> None:
        total = int(p.get("total") or 0)
        if total > 1:
            ok = int(p.get("succeeded") or 0)
            _log(f"[crew] done  {ok}/{total} succeeded")

    def _on_error(self, p: dict[str, Any]) -> None:
        msg = str(p.get("message") or p.get("error") or "error")
        _log(f"[kite] error  {msg[:300]}")

    def _on_stream_delta(self, p: dict[str, Any]) -> None:
        if not self.verbose:
            return
        text = str(p.get("text") or p.get("delta") or "")
        if text:
            _log(f"[stream] {text.rstrip()}")

    def _on_stream_reasoning(self, p: dict[str, Any]) -> None:
        if not self.verbose:
            return
        text = str(p.get("text") or "")
        if text:
            _log(f"[reason] {text.rstrip()}")

    def _on_stream_first_token(self, p: dict[str, Any]) -> None:
        if not self.verbose:
            return
        ttft = int(p.get("ttft_ms") or 0)
        channel = str(p.get("channel") or "answer")
        _log(f"[stream] first token  {channel}  {ttft}ms")

    def _on_stream_usage(self, p: dict[str, Any]) -> None:
        if not self.verbose:
            return
        out = int(p.get("completion_tokens") or p.get("output_tokens") or 0)
        if out:
            _log(f"[stream] usage  out={out}")


@dataclass
class HeadlessTaskResult:
    index: int
    label: str
    ok: bool
    exit_status: str
    session_id: str
    submission: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "ok": self.ok,
            "exit_status": self.exit_status,
            "session_id": self.session_id,
            "submission": self.submission[:2000],
            "error": self.error,
        }


@dataclass
class HeadlessBatchResult:
    ok: bool
    results: list[HeadlessTaskResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total": len(self.results),
            "succeeded": sum(1 for r in self.results if r.ok),
            "results": [r.to_dict() for r in self.results],
        }


def _headless_todos(harness: Any) -> list[dict[str, Any]]:
    """Best-effort live todos for the continuity brief (runtime owns the store)."""
    for obj in (getattr(harness, "_runtime", None), harness):
        read = getattr(getattr(obj, "todos", None), "read", None)
        if not callable(read):
            continue
        try:
            rows = read()
        except Exception:
            continue
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _emit_limit_brief(*, harness: Any, task_label: str, exit_status: str) -> str:
    """Log mission/done/next/todos + resume hint for a non-success exit.

    Returns the resume-hint string ("" when no session exists) so callers can
    attach it to the result error. Never raises — briefs must not mask exits.
    """
    try:
        session = getattr(harness, "last_session", None)
        sid = str(getattr(session, "id", None) or getattr(session, "session_id", None) or "")
    except Exception:
        session, sid = None, ""
    messages: list[dict[str, Any]] = []
    if session is not None:
        try:
            raw = getattr(session, "messages", None) or []
            messages = [m for m in list(raw) if isinstance(m, dict)]
        except Exception:
            messages = []
    try:
        from kite.memory.handoff import resume_command

        hint = resume_command(sid, "continue from checkpoint") if sid else ""
    except Exception:
        hint = f'kite resume {sid} "continue from checkpoint"' if sid else ""
    if not messages and not sid:
        return hint
    if exit_status in _LIMIT_BRIEF_EXITS and messages:
        try:
            from kite.memory.continuity import build_continuity_brief

            brief = build_continuity_brief(
                messages=messages, todos=_headless_todos(harness), task=task_label
            )
            for line in brief.to_markdown().strip().splitlines():
                _log(f"[continuity] {line}")
        except Exception:
            pass
    if hint:
        _log(f"[kite] resume  {hint}")
    return hint


def _with_resume_hint(error: str, hint: str) -> str:
    if not hint or hint in error:
        return error
    return f"{error}; resume: {hint}" if error else f"resume: {hint}"


def resolve_headless_approval(raw: str | None, mode: AgentMode, *, headless: bool) -> ApprovalMode:
    """Pick approval for non-interactive runs without weakening user policy."""
    default = ApprovalMode.AUTO if mode is AgentMode.BUILD else ApprovalMode.READONLY
    approval = parse_approval_mode(raw, default=default)
    return approval


def run_headless_task(
    task: HeadlessTask,
    *,
    provider: str | None = None,
    model: str | None = None,
    config_name: str | Path | None = None,
    stream_tools: bool = True,
    verbose: bool = False,
    no_context: bool = False,
    no_compact: bool = False,
    no_guardrails: bool = False,
    step_limit: int | None = None,
    cost_limit: float | None = None,
    wall_time_limit_seconds: int = 0,
) -> HeadlessTaskResult:
    from kite.agent.harness import Harness
    from kite.agent.harness_build import build_harness_config
    from kite.application.cli import execute_harness_task, legacy_result_from_run

    cwd = str(Path(task.cwd or ".").expanduser().resolve())
    try:
        mode = AgentMode(task.mode)
    except ValueError:
        mode = AgentMode.BUILD
    approval = resolve_headless_approval(task.approval, mode, headless=True)
    harness = Harness(
        build_harness_config(
            provider=provider,
            model_name=model,
            cwd=cwd,
            label=task.label or "headless",
            mode=mode.value,
            approval=approval.value,
            interactive=False,
            role=task.role,
            long_task=task.long_task,
            no_context=no_context,
            no_compact=no_compact,
            no_guardrails=no_guardrails,
            config_name=config_name,
            step_limit=step_limit,
            cost_limit=cost_limit,
            wall_time_limit_seconds=wall_time_limit_seconds or 0,
        )
    )
    from kite.config import load_runtime_config
    from kite.ui.approval import make_approver
    from kite.ui.style import make_console

    runtime_config = load_runtime_config(config_name)
    harness.approver = make_approver(
        make_console(stderr=True),
        mode=mode,
        approval=approval,
        interactive=False,
        trusted_paths=runtime_config.guardrails.trusted_paths,
        workspace_cwd=cwd,
    )
    display = HeadlessRunDisplay(stream_tools=stream_tools, verbose=verbose)
    harness.subscribe(display)
    label = task.label or task.task[:48].replace("\n", " ")
    _log(f"[task] {label}")
    killed = 0
    legacy: dict[str, Any] | None = None
    error_text = ""
    try:
        run_result = execute_harness_task(harness, task.task)
        legacy = legacy_result_from_run(run_result)
    except Exception as e:
        error_text = str(e)
    finally:
        killed = harness.teardown_jobs() or 0
    sid = harness.last_session.id if harness.last_session else ""
    if legacy is None:
        extra = f"stopped {killed} leftover background job(s)" if killed else ""
        err = f"{error_text}; {extra}" if error_text and extra else (error_text or extra or "no result")
        err = _with_resume_hint(
            err, _emit_limit_brief(harness=harness, task_label=label, exit_status="Error")
        )
        return HeadlessTaskResult(
            index=0,
            label=label,
            ok=False,
            exit_status="Error",
            session_id=sid,
            error=err,
        )
    exit_status = str(legacy.get("exit_status") or "Error")
    ok = exit_status == "Submitted" and killed == 0
    error = str(legacy.get("error") or "")
    if killed:
        extra = f"stopped {killed} leftover background job(s)"
        error = f"{error}; {extra}" if error else extra
    if not ok:
        # Budget/stall/fault exits end with mission/done/next/todos + resume
        # hint on stderr so headless runs never go silent on long tasks.
        error = _with_resume_hint(
            error,
            _emit_limit_brief(harness=harness, task_label=label, exit_status=exit_status),
        )
    return HeadlessTaskResult(
        index=0,
        label=label,
        ok=ok,
        exit_status=exit_status if killed == 0 else (exit_status if exit_status != "Submitted" else "Error"),
        session_id=sid,
        submission=str(legacy.get("submission") or legacy.get("content") or ""),
        error=error,
    )


def run_headless_batch(
    tasks: list[HeadlessTask],
    *,
    continue_on_error: bool = False,
    **kwargs: Any,
) -> HeadlessBatchResult:
    results: list[HeadlessTaskResult] = []
    batch_ok = True
    for index, task in enumerate(tasks):
        result = run_headless_task(task, **kwargs)
        result = HeadlessTaskResult(
            index=index,
            label=result.label or task.label or f"task-{index + 1}",
            ok=result.ok,
            exit_status=result.exit_status,
            session_id=result.session_id,
            submission=result.submission,
            error=result.error,
        )
        results.append(result)
        if not result.ok:
            batch_ok = False
            if not continue_on_error:
                break
    return HeadlessBatchResult(ok=batch_ok, results=results)
