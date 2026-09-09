"""Headless task runs — structured stderr logging without a TTY."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode, default_approval, parse_approval_mode
from kite.util.tty import is_interactive_tty


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
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "agent_start": self._on_agent_start,
            "agent_end": self._on_agent_end,
            "tool_start": self._on_tool_start,
            "tool_end": self._on_tool_end,
            "tool_output": self._on_tool_output,
            "job_output": self._on_job_output,
            "subagent_start": self._on_subagent_start,
            "subagent_end": self._on_subagent_end,
            "orchestrator_start": self._on_orchestrator_start,
            "orchestrator_end": self._on_orchestrator_end,
            "error": self._on_error,
            "stream_delta": self._on_stream_delta,
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

    def _on_agent_start(self, p: dict[str, Any]) -> None:
        label = str(p.get("label") or "").strip()
        suffix = f"  {label}" if label else ""
        _log(f"[kite] start{suffix}")

    def _on_agent_end(self, p: dict[str, Any]) -> None:
        status = str(p.get("exit_status") or p.get("status") or "done")
        _log(f"[kite] end  {status}")

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


def resolve_headless_approval(raw: str | None, mode: AgentMode, *, headless: bool) -> ApprovalMode:
    """Pick approval for non-interactive runs without weakening user policy."""
    approval = parse_approval_mode(raw, default=default_approval(mode))
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
) -> HeadlessTaskResult:
    from kite.agent.harness import Harness
    from kite.agent.harness_build import build_harness_config
    from kite.application.cli.runner import execute_harness_task, legacy_result_from_run

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
    try:
        run_result = execute_harness_task(harness, task.task)
        legacy = legacy_result_from_run(run_result)
    except Exception as e:
        return HeadlessTaskResult(
            index=0,
            label=label,
            ok=False,
            exit_status="Error",
            session_id="",
            error=str(e),
        )
    finally:
        harness.teardown_jobs()
    sid = harness.last_session.id if harness.last_session else ""
    exit_status = str(legacy.get("exit_status") or "Error")
    ok = exit_status in {"Submitted", "LimitsExceeded", "Stalled"}
    return HeadlessTaskResult(
        index=0,
        label=label,
        ok=ok,
        exit_status=exit_status,
        session_id=sid,
        submission=str(legacy.get("submission") or legacy.get("content") or ""),
        error=str(legacy.get("error") or ""),
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
