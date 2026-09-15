"""Subagent orchestrator — manager view for parallel LLM workers against a plan."""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any

from kite.agent.cancel import CancelToken
from kite.agent.dispatch_mode import dispatch_hint, resolve_dispatch_mode
from kite.agent.events import Event

_SUCCESS_EXIT = frozenset({"Submitted"})
_USEFUL_EXIT = frozenset({"LimitsExceeded", "Stalled"})
_FAILURE_EXIT = frozenset({"Error", "ProviderFault", "Interrupted"})
_WORKER_GLYPHS = ("◆", "●", "◇", "▲", "▶", "★")
_MIN_USEFUL_CHARS = 40
_SECTION_LIMIT = 2000
_MAX_FINISHED_TASKS = 64
_MAX_CREW_SIZE = 12
_MAX_SUBAGENT_DEPTH = 1  # Codex-style: workers cannot nest further by default
_DEFAULT_MAX_SPAWNS = 64  # Pi-style cap on cumulative workers per run tree
_MAX_PROMPT_CHARS = 8000
_MAX_LABEL_CHARS = 80
_MANAGER_EVENT_LIMIT = 8


def worker_glyph(index: int) -> str:
    """Rotate glyphs so parallel workers are easy to spot in the TUI."""
    return _WORKER_GLYPHS[(max(1, index) - 1) % len(_WORKER_GLYPHS)]


def _sanitize_label(text: str, fallback: str = "worker") -> str:
    clean = re.sub(r"[\x00-\x1f\x7f]", "", (text or "").strip())
    clean = clean[:_MAX_LABEL_CHARS].strip()
    return clean or fallback


def _clamp_prompt(text: str) -> str:
    raw = (text or "").strip()
    if len(raw) <= _MAX_PROMPT_CHARS:
        return raw
    return raw[: _MAX_PROMPT_CHARS - 3] + "..."


def evaluate_subagent_result(result: dict[str, Any]) -> tuple[bool, str, str]:
    """Return (ok, quality, summary). quality: done | partial | failed | killed.

    Rubric: done only with sections or Submitted exit; partial when submission
    lacks Result/Files sections or LimitsExceeded/Stalled without evidence;
    failed when submission empty with non-success exit, or provider failure.
    """
    if result.get("cancelled"):
        return False, "killed", "cancelled"
    submission = str(result.get("submission") or result.get("content") or "").strip()
    status = str(result.get("exit_status") or "done")
    if status in _SUCCESS_EXIT:
        return True, "done", submission or f"finished ({status})"
    if status in _FAILURE_EXIT:
        return False, "failed", submission or str(result.get("error") or f"failed ({status})")
    if not submission:
        return False, "failed", f"finished with {status} (no summary text)"
    if _has_summary_sections(submission):
        return True, "done", submission
    return True, "partial", submission


def _has_summary_sections(text: str) -> bool:
    lowered = (text or "").lower()
    has_result = bool(re.search(r"##\s*result", lowered))
    has_files = bool(re.search(r"##\s*files touched", lowered))
    return has_result and has_files


def summarize_result(text: str, *, limit: int = _SECTION_LIMIT) -> str:
    """Clamp overlong submissions with head/tail preservation."""
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    overflow = len(raw) - limit
    marker = f"\n…[truncated {overflow} chars]…\n"
    keep = max(0, limit - len(marker))
    head = (keep * 2) // 3
    tail = keep - head
    if tail > 0:
        return raw[:head] + marker + raw[-tail:]
    return raw[:head] + marker


def _extract_touched_paths(result: dict[str, Any]) -> list[str]:
    for key in ("files_touched", "touched_files", "touched_paths", "files"):
        raw = result.get(key)
        if isinstance(raw, (list, tuple)):
            return [str(x).strip() for x in raw if str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            return [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]
    submission = str(result.get("submission") or result.get("content") or "")
    if not submission:
        return []
    match = re.search(r"##\s*files touched(.*)", submission, re.IGNORECASE | re.DOTALL)
    section = match.group(1) if match else ""
    if match:
        section = re.split(r"\n##\s+", section, maxsplit=1)[0]
    paths: list[str] = []
    for line in section.splitlines():
        cleaned = line.strip().lstrip("-*•0123456789. ").strip().strip("`'\"")
        if not cleaned or len(cleaned) > 500 or " " in cleaned.strip().split("\n")[0] and "." not in cleaned:
            if not re.match(r"^[\w\-./\\]+$", cleaned):
                continue
        if re.match(r"^[\w\-./\\:]+$", cleaned):
            paths.append(cleaned)
    return paths


def gate_result(task: SubagentTask, result: dict[str, Any] | None) -> str:
    """Return blocking reason when touched paths fall outside task scope (prefix check)."""
    scope = getattr(task, "scope", None)
    if not scope:
        return ""
    scopes = [scope] if isinstance(scope, str) else list(scope)
    scopes = [str(s).replace("\\", "/").strip().rstrip("/") for s in scopes if str(s).strip()]
    if not scopes:
        return ""
    touched = _extract_touched_paths(result or {})
    for path in touched:
        norm = path.replace("\\", "/").strip().lstrip("./")
        if not any(norm == s or norm.startswith(s.rstrip("/") + "/") for s in scopes):
            return f"out-of-scope write blocked: '{path}' outside scope {scopes}"
    return ""


def _resolve_repo_contract() -> tuple[str, str]:
    try:
        from pathlib import Path

        from kite.context.discovery import find_project_root

        cwd = Path.cwd()
        return str(find_project_root(cwd)), str(cwd)
    except Exception:
        return "", ""


def _revise_prompt(base: str, reason: str) -> str:
    note = (reason or "").strip()[:1000]
    revised = f"{(base or '').rstrip()}\n\n## Revise (retry 1/1)\n{note}\nAddress the issue and resubmit per summary contract."
    return _clamp_prompt(revised)


def _normalize_scope(scope: list[str] | str | None) -> list[str] | None:
    if scope is None:
        return None
    items = [scope] if isinstance(scope, str) else list(scope)
    cleaned = [str(s).strip() for s in items if str(s).strip()]
    return cleaned or None


def _scope_arg_list(args: dict[str, Any], n: int) -> list[list[str] | None]:
    raw = args.get("scopes")
    if isinstance(raw, list) and raw:
        out: list[list[str] | None] = []
        for item in raw:
            out.append(_normalize_scope(item if isinstance(item, list) else str(item or "")))
        while len(out) < n:
            out.append(out[-1] if out else None)
        return out[:n]
    single = _normalize_scope(args.get("scope"))  # type: ignore[arg-type]
    return [single] * n


def _str_arg_list(args: dict[str, Any], key: str) -> list[str] | None:
    raw = args.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return None


def _repeat_or_none(single: str, n: int) -> list[str] | None:
    return [single] * n if single else None


def _label_list(args: dict[str, Any]) -> list[str] | None:
    labels = args.get("labels")
    if isinstance(labels, list):
        return [str(x) for x in labels]
    return None


def _timeout_list(args: dict[str, Any], n: int) -> list[float | None] | None:
    raw = args.get("timeouts")
    if not isinstance(raw, list):
        return None
    out: list[float | None] = []
    for x in raw[:n]:
        try:
            out.append(None if x is None or x == "" else float(x))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            out.append(None)
    while len(out) < n:
        out.append(None)
    return out


def _timeout_single(args: dict[str, Any]) -> float | None:
    raw = args.get("timeout_s")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _abort_flag(args: dict[str, Any]) -> bool:
    return bool(args.get("abort_on_failure") or args.get("abortOnFailure"))


def _parent_run(args: dict[str, Any]) -> tuple[str, str]:
    parent = str(args.get("parent_id") or "")
    run = str(args.get("run_id") or args.get("parent_run_id") or "")
    return parent, run


def _format_sections(
    header: str,
    rows: list[tuple[str, bool, str, str, int | None]],
) -> str:
    lines = [header]
    for label, ok, quality, body, elapsed_ms in rows:
        mark = "✓" if ok else "✗"
        timing = f" · {elapsed_ms}ms" if elapsed_ms else ""
        detail = f" ({quality})" if quality not in {"done", "failed"} else ""
        lines.append(f"\n--- {mark} {label}{detail}{timing} ---\n{summarize_result(body)}")
    return "\n".join(lines)


@dataclass
class SubagentTask:
    id: str
    prompt: str
    label: str
    profile: str = ""
    role: str = ""
    status: str = "queued"  # queued | running | finished | failed | killed
    exit_status: str = ""
    summary: str = ""
    ok: bool = False
    quality: str = ""
    worker: int = 0
    glyph: str = "◆"
    started_at: float = 0.0
    elapsed_ms: int = 0
    background: bool = False
    provider: str = ""
    model: str = ""
    scope: list[str] | None = None
    retryable: bool = True
    context: str = ""
    retried: bool = False
    parent_id: str = ""
    run_id: str = ""
    timeout_s: float | None = None
    cancel: CancelToken | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        row = {
            "id": self.id,
            "label": self.label,
            "profile": self.profile,
            "role": self.role,
            "status": self.status,
            "exit_status": self.exit_status,
            "ok": self.ok,
            "quality": self.quality or self.status,
            "summary": self.summary[:200],
            "worker": self.worker,
            "glyph": self.glyph,
            "elapsed_ms": self.elapsed_ms,
            "background": self.background,
        }
        if self.provider:
            row["provider"] = self.provider
        if self.model:
            row["model"] = self.model
        if self.parent_id:
            row["parent_id"] = self.parent_id
        if self.run_id:
            row["run_id"] = self.run_id
        return row

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.summary,
            "subagent_id": self.id,
            "exit_status": self.exit_status,
            "quality": self.quality or self.status,
            "elapsed_ms": self.elapsed_ms,
            "background": self.background,
        }


_REGISTRY_LOCK = threading.Lock()
_TASK_REGISTRY: dict[str, SubagentTask] = {}


def register_task(task: SubagentTask) -> SubagentTask:
    """Track a task in the in-memory thread-tree registry (no persistence)."""
    with _REGISTRY_LOCK:
        _TASK_REGISTRY[task.id] = task
    return task


def unregister_task(task_id: str) -> bool:
    """Remove a task from the registry; return True when something was removed."""
    with _REGISTRY_LOCK:
        return _TASK_REGISTRY.pop(task_id, None) is not None


def get_registered_task(task_id: str) -> SubagentTask | None:
    with _REGISTRY_LOCK:
        return _TASK_REGISTRY.get(task_id)


def list_children(parent_id: str) -> list[SubagentTask]:
    """Return registered tasks whose parent_id matches (thread-tree siblings)."""
    if not parent_id:
        return []
    with _REGISTRY_LOCK:
        return [t for t in _TASK_REGISTRY.values() if t.parent_id == parent_id]


def clear_registry() -> None:
    """Test helper: drop all in-memory thread-tree entries."""
    with _REGISTRY_LOCK:
        _TASK_REGISTRY.clear()


@dataclass
class SubagentOrchestrator:
    """Dispatch bounded nested agent runs; emit manager events for the TUI.

    Bounds (sweet spot is 3-5 workers; hard cap is 12 per dispatch):
    - per-dispatch crew cap ``_MAX_CREW_SIZE`` (12)
    - nesting depth cap ``_MAX_SUBAGENT_DEPTH`` (1) — dispatch(depth>=1) is blocked
      unless ``allow_nested`` is set; worker registries never contain the subagent
      tool either, so nesting is structurally blocked one level down
    - cumulative spawn budget ``max_spawns`` (64) per run tree, shared by every
      entry point on this instance
    """

    runner: Callable[..., dict[str, Any]]
    on_event: Callable[[Event], None] | None = None
    max_workers: int = 3
    timeout_seconds: int = 300
    tasks: list[SubagentTask] = field(default_factory=list)
    jobs: Any | None = None  # JobRegistry | None
    depth: int = 0  # nesting level of this orchestrator (0 = top-level run)
    max_spawns: int = _DEFAULT_MAX_SPAWNS
    allow_nested: bool = False
    _worker_seq: int = 0
    _spawn_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _runner_pool: ThreadPoolExecutor | None = field(default=None, repr=False)

    @property
    def spawn_count(self) -> int:
        """Cumulative workers spawned on this instance (budget accounting)."""
        with self._lock:
            return self._spawn_count

    def _budget_message(self, n: int) -> str:
        """Error text when ``n`` more workers would exceed the run-tree budget."""
        return (
            f"spawn budget exceeded ({self._spawn_count + n}/{self.max_spawns} workers "
            "in this run tree); split the work or raise max_spawns"
        )

    def _check_spawn_budget(self, n: int) -> str:
        """Peek: "" when ``n`` more workers fit, else an error message (no accounting change)."""
        with self._lock:
            if self._spawn_count + n > self.max_spawns:
                return self._budget_message(n)
            return ""

    def _reserve_spawns(self, n: int) -> str:
        """Reserve ``n`` budget slots; return "" on success or an error message."""
        with self._lock:
            if self._spawn_count + n > self.max_spawns:
                return self._budget_message(n)
            self._spawn_count += n
            return ""

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def _runner_executor(self) -> ThreadPoolExecutor:
        if self._runner_pool is None:
            self._runner_pool = ThreadPoolExecutor(max_workers=max(1, self.max_workers))
        return self._runner_pool

    def manager_view(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.tasks]

    def _manager_payload(self, *, limit: int = _MANAGER_EVENT_LIMIT) -> list[dict[str, Any]]:
        running = [t for t in self.tasks if t.status == "running"]
        finished = [t for t in self.tasks if t.status not in {"running", "queued"}]
        finished.sort(key=lambda t: t.started_at, reverse=True)
        combined = running + finished
        return [t.to_dict() for t in combined[:limit]]

    def _task_by_id(self, task_id: str) -> SubagentTask | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def _next_worker(self) -> tuple[int, str]:
        with self._lock:
            self._worker_seq += 1
            return self._worker_seq, worker_glyph(self._worker_seq)

    def _call_runner(self, task: SubagentTask) -> dict[str, Any]:
        from kite.agent.subagent_profiles import (
            SUMMARY_CONTRACT,
            get_profile,
            resolve_subagent_task,
            worker_tool_allowlist,
        )

        cancel = task.cancel
        assert cancel is not None
        project_root, execution_cwd = _resolve_repo_contract()
        composed, resolved_role, resolved_label = resolve_subagent_task(
            prompt=task.prompt,
            profile=task.profile,
            role=task.role,
            label=task.label,
            context=task.context,
            project_root=project_root,
            execution_cwd=execution_cwd,
        )
        if SUMMARY_CONTRACT not in composed:
            composed = f"{composed}\n\n{SUMMARY_CONTRACT}"
        if resolved_label:
            task.label = resolved_label
        if resolved_role:
            task.role = resolved_role
        profile = get_profile(task.profile) if task.profile else None
        kwargs = {
            "cancel": cancel,
            "profile": task.profile,
            "role": resolved_role,
            "label": task.label,
            "subagent_id": task.id,
            "glyph": task.glyph,
            "provider": task.provider,
            "model": task.model,
            "model_role": profile.model_role if profile else "",
            "allowed_tools": worker_tool_allowlist(profile),
        }
        try:
            return self.runner(composed, **kwargs)
        except TypeError:
            try:
                return self.runner(composed, cancel=cancel)
            except TypeError:
                return self.runner(composed)

    def _effective_timeout(self, task: SubagentTask) -> float:
        if task.timeout_s is not None:
            return float(task.timeout_s)
        return float(self.timeout_seconds)

    def _run_with_timeout(self, task: SubagentTask) -> dict[str, Any]:
        effective = self._effective_timeout(task)
        if effective <= 0:
            return self._call_runner(task)
        pool = self._runner_executor()
        fut: Future[dict[str, Any]] = pool.submit(self._call_runner, task)
        cancel = task.cancel
        assert cancel is not None
        return fut.result(timeout=effective)

    def _result_payload(self, task: SubagentTask, **fields: Any) -> dict[str, Any]:
        return {
            "subagent_id": task.id,
            "elapsed_ms": task.elapsed_ms,
            "background": task.background,
            "manager": self.manager_view(),
            **fields,
        }

    def _finish_task(
        self,
        task: SubagentTask,
        *,
        runner_result: dict[str, Any] | None = None,
        error: str = "",
        cancelled: bool = False,
        timed_out: bool = False,
        timeout_value: float | None = None,
    ) -> dict[str, Any]:
        started = task.started_at or time.monotonic()
        task.elapsed_ms = int((time.monotonic() - started) * 1000)

        if cancelled:
            task.status = "killed"
            task.quality = "killed"
            task.summary = "cancelled"
            task.ok = False
            return self._result_payload(
                task,
                ok=False,
                output="cancelled",
                error="cancelled",
                cancelled=True,
                quality="killed",
            )

        if timed_out:
            task.status = "failed"
            task.quality = "failed"
            limit = timeout_value if timeout_value is not None else self._effective_timeout(task)
            task.summary = f'"{task.label}" timed out after {limit}s'
            task.ok = False
            return self._result_payload(
                task,
                ok=False,
                output=task.summary,
                error="timeout",
                quality="failed",
            )

        if error:
            task.status = "failed"
            task.quality = "failed"
            task.summary = error
            task.ok = False
            return self._result_payload(
                task,
                ok=False,
                output=error,
                error=error,
                quality="failed",
            )

        result = runner_result or {}
        ok, quality, summary = evaluate_subagent_result(result)
        status = str(result.get("exit_status") or "done")
        task.exit_status = status
        task.summary = summarize_result(summary, limit=4000) if summary else f"finished ({status})"
        task.quality = quality
        task.ok = ok
        task.status = "finished" if ok else "failed"
        return self._result_payload(
            task,
            ok=ok,
            output=task.summary,
            exit_status=status,
            quality=quality,
        )

    def _prune_finished_tasks(self) -> None:
        finished = [t for t in self.tasks if t.status not in {"running", "queued"}]
        if len(finished) <= _MAX_FINISHED_TASKS:
            return
        finished.sort(key=lambda t: t.started_at)
        drop = {t.id for t in finished[: len(finished) - _MAX_FINISHED_TASKS]}
        if drop:
            self.tasks = [t for t in self.tasks if t.id not in drop]
            for tid in drop:
                unregister_task(tid)

    def _mark_job_done(self, task: SubagentTask, out: dict[str, Any]) -> None:
        if self.jobs is None:
            return
        existing = self.jobs.get(task.id)
        if existing is None:
            return
        if existing.status == "running":
            self.jobs.mark_done(
                task.id,
                ok=bool(out.get("ok")),
                status="killed" if out.get("cancelled") else None,
                result_payload=out,
            )
        else:
            self.jobs.set_subagent_result(task.id, out)

    def _execute_task(self, task: SubagentTask) -> dict[str, Any]:
        cancel = task.cancel
        assert cancel is not None
        try:
            result = self._run_with_timeout(task)
            if cancel.is_set():
                out = self._finish_task(task, cancelled=True)
            else:
                out = self._finish_task(task, runner_result=result)
                out = self._maybe_revise(task, result, out)
        except FuturesTimeout:
            cancel.request()
            out = self._finish_task(task, timed_out=True, timeout_value=self._effective_timeout(task))
        except Exception as e:
            out = self._finish_task(task, error=str(e))

        self._mark_job_done(task, out)
        self._prune_finished_tasks()
        self._emit(
            "subagent_end",
            id=task.id,
            label=task.label,
            thread=f"{task.glyph} {task.label}",
            profile=task.profile,
            role=task.role,
            ok=out.get("ok", False),
            quality=out.get("quality", ""),
            preview=str(out.get("output") or "")[:120],
            elapsed_ms=out.get("elapsed_ms", task.elapsed_ms),
            worker=task.worker,
            glyph=task.glyph,
            background=task.background,
            parent_id=task.parent_id,
            run_id=task.run_id,
            manager=self._manager_payload(),
        )
        return out

    def _maybe_revise(
        self,
        task: SubagentTask,
        result: dict[str, Any],
        out: dict[str, Any],
    ) -> dict[str, Any]:
        """One-shot revise loop: exactly one re-dispatch when gated failed/partial."""
        if task.retried or not task.retryable:
            return out
        if task.quality not in {"failed", "partial"}:
            return out
        reason = gate_result(task, result) or f"quality={task.quality}: {task.summary[:500]}"
        task.retried = True
        task.prompt = _revise_prompt(task.prompt, reason)
        try:
            retry_result = self._run_with_timeout(task)
        except FuturesTimeout:
            if task.cancel is not None:
                task.cancel.request()
            return self._finish_task(task, timed_out=True, timeout_value=self._effective_timeout(task))
        except Exception as e:
            return self._finish_task(task, error=str(e))
        if task.cancel is not None and task.cancel.is_set():
            return self._finish_task(task, cancelled=True)
        return self._finish_task(task, runner_result=retry_result)

    def _begin_task(
        self,
        prompt: str,
        *,
        label: str = "",
        profile: str = "",
        role: str = "",
        worker: int = 0,
        glyph: str = "",
        background: bool = False,
        provider: str = "",
        model: str = "",
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        context: str = "",
        scope: list[str] | str | None = None,
        retryable: bool = True,
    ) -> SubagentTask:
        tid = uuid.uuid4().hex[:8]
        prompt = _clamp_prompt(prompt)
        title = _sanitize_label(label, prompt[:60].replace("\n", " ") or "worker")
        if not worker:
            worker, glyph = self._next_worker()
        cancel = CancelToken()
        task = SubagentTask(
            id=tid,
            prompt=prompt,
            label=title,
            profile=profile,
            role=role,
            status="running",
            cancel=cancel,
            worker=worker,
            glyph=glyph or worker_glyph(worker),
            started_at=time.monotonic(),
            background=background,
            provider=provider,
            model=model,
            parent_id=parent_id,
            run_id=run_id,
            timeout_s=timeout_s,
            context=(context or "")[:2000],
            scope=_normalize_scope(scope),
            retryable=bool(retryable),
        )
        self.tasks.append(task)
        register_task(task)
        if self.jobs is not None:
            self.jobs.register_subagent(
                job_id=tid,
                label=title,
                prompt=prompt,
                profile=profile,
                cancel=cancel,
            )
        self._emit(
            "subagent_start",
            id=tid,
            label=title,
            thread=f"{task.glyph} {title}",
            profile=profile,
            role=role,
            prompt=prompt[:240],
            worker=worker,
            glyph=task.glyph,
            background=background,
            parent_id=parent_id,
            run_id=run_id,
            manager=self._manager_payload(),
        )
        return task

    def _run_worker(
        self,
        prompt: str,
        *,
        label: str,
        profile: str = "",
        role: str = "",
        worker: int,
        glyph: str,
        provider: str = "",
        model: str = "",
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        context: str = "",
        scope: list[str] | str | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        task = self._begin_task(
            prompt,
            label=label,
            profile=profile,
            role=role,
            worker=worker,
            glyph=glyph,
            background=False,
            provider=provider,
            model=model,
            parent_id=parent_id,
            run_id=run_id,
            timeout_s=timeout_s,
            context=context,
            scope=scope,
            retryable=retryable,
        )
        return self._execute_task(task)

    def run_one(
        self,
        prompt: str,
        *,
        label: str = "",
        profile: str = "",
        role: str = "",
        worker: int = 0,
        glyph: str = "",
        provider: str = "",
        model: str = "",
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        context: str = "",
        scope: list[str] | str | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        budget_error = self._reserve_spawns(1)
        if budget_error:
            return {"ok": False, "error": budget_error, "output": budget_error}
        if not worker:
            worker, glyph = self._next_worker()
        return self._run_worker(
            prompt,
            label=label or prompt[:60].replace("\n", " "),
            profile=profile,
            role=role,
            worker=worker,
            glyph=glyph,
            provider=provider,
            model=model,
            parent_id=parent_id,
            run_id=run_id,
            timeout_s=timeout_s,
            context=context,
            scope=scope,
            retryable=retryable,
        )

    def run_one_background(
        self,
        prompt: str,
        *,
        label: str = "",
        profile: str = "",
        role: str = "",
        provider: str = "",
        model: str = "",
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        context: str = "",
        scope: list[str] | str | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        budget_error = self._reserve_spawns(1)
        if budget_error:
            return {"ok": False, "error": budget_error, "output": budget_error}
        task = self._begin_task(
            prompt,
            label=label,
            profile=profile,
            role=role,
            background=True,
            provider=provider,
            model=model,
            parent_id=parent_id,
            run_id=run_id,
            timeout_s=timeout_s,
            context=context,
            scope=scope,
            retryable=retryable,
        )

        def _work() -> None:
            self._execute_task(task)

        threading.Thread(target=_work, daemon=True, name=f"kite-subagent-{task.id}").start()
        return {
            "ok": True,
            "background": True,
            "dispatch": "async",
            "job_id": task.id,
            "subagent_id": task.id,
            "label": task.label,
            "output": (
                f"background worker {task.id} · {task.label}\n"
                f'Collect with wait_for: ["{task.id}"] or check /agents'
            ),
            "manager": self.manager_view(),
        }

    def wait_for(self, job_ids: list[str], *, timeout_seconds: float = 300.0) -> dict[str, Any]:
        ids = [str(x).strip() for x in job_ids if str(x).strip()]
        if not ids:
            msg = "wait_for needs at least one job_id from a background worker"
            return {"ok": False, "error": msg, "output": msg}

        deadline = time.monotonic() + max(1.0, timeout_seconds)
        collected: dict[str, dict[str, Any]] = {}
        pending = set(ids)

        while pending and time.monotonic() < deadline:
            for jid in list(pending):
                task = self._task_by_id(jid)
                if task is not None and task.status not in {"running", "queued"}:
                    collected[jid] = task.as_result()
                    pending.discard(jid)
                    continue
                if self.jobs is not None:
                    job = self.jobs.get(jid)
                    if job is not None and job.result_payload is not None:
                        collected[jid] = dict(job.result_payload)
                        pending.discard(jid)
                    elif job is not None and job.status != "running" and job.kind == "subagent":
                        payload = job.result_payload or {}
                        collected[jid] = {
                            "ok": bool(payload.get("ok", job.status == "done")),
                            "output": str(payload.get("output") or job.log_text()[:_SECTION_LIMIT] or f"exit={job.status}"),
                            "subagent_id": jid,
                            "quality": str(payload.get("quality") or job.status),
                        }
                        pending.discard(jid)
            if pending:
                time.sleep(0.1)

        rows: list[tuple[str, bool, str, str, int | None]] = []
        for jid in ids:
            if jid in collected:
                r = collected[jid]
                rows.append(
                    (
                        jid,
                        bool(r.get("ok")),
                        str(r.get("quality") or ("done" if r.get("ok") else "failed")),
                        str(r.get("output") or ""),
                        int(r.get("elapsed_ms") or 0) or None,
                    )
                )
            else:
                rows.append((jid, False, "pending", "(still running or unknown id)", None))

        ok = not pending and all(r.get("ok") for r in collected.values())
        header = f"collected · {len(collected)}/{len(ids)} ready"
        if pending:
            header += f" · timed out waiting for: {', '.join(sorted(pending))}"
        return {
            "ok": ok,
            "output": _format_sections(header, rows),
            "pending": sorted(pending),
            "timed_out": sorted(pending),
            "results": collected,
            "dispatch": "collect",
        }

    def run_parallel(
        self,
        prompts: list[str],
        *,
        labels: list[str] | None = None,
        profiles: list[str] | None = None,
        roles: list[str] | None = None,
        providers: list[str] | None = None,
        models: list[str] | None = None,
        abort_on_failure: bool = False,
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        timeouts: list[float | None] | None = None,
        contexts: list[str] | None = None,
        scope: list[str] | str | None = None,
        scopes: list[list[str] | str | None] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        if not prompts:
            return {"ok": False, "error": "prompts required", "output": "prompts required"}
        if len(prompts) > _MAX_CREW_SIZE:
            msg = f"crew too large ({len(prompts)}); max {_MAX_CREW_SIZE} workers per dispatch"
            return {"ok": False, "error": msg, "output": msg}
        budget_error = self._reserve_spawns(len(prompts))
        if budget_error:
            return {"ok": False, "error": budget_error, "output": budget_error}
        workers = min(self.max_workers, len(prompts))
        labels = labels or [f"worker-{i}" for i in range(1, len(prompts) + 1)]
        profiles = profiles or [""] * len(prompts)
        roles = roles or [""] * len(prompts)
        providers = providers or [""] * len(prompts)
        models = models or [""] * len(prompts)
        contexts = contexts or [""] * len(prompts)
        crew_scopes = list(scopes) if scopes else [_normalize_scope(scope)] * len(prompts)
        crew_run = run_id or uuid.uuid4().hex[:8]
        self._emit(
            "orchestrator_start",
            total=len(prompts),
            workers=workers,
            labels=labels[: len(prompts)],
            dispatch="sync",
            parent_id=parent_id,
            run_id=crew_run,
        )
        results: dict[int, dict[str, Any]] = {}
        worker_slots = [self._next_worker() for _ in prompts]

        def _timeout_for(i: int) -> float | None:
            if timeouts is not None and i - 1 < len(timeouts):
                return timeouts[i - 1]
            return timeout_s

        crew: list[SubagentTask] = []
        for i, p in enumerate(prompts, 1):
            crew.append(
                self._begin_task(
                    str(p),
                    label=str(labels[i - 1]),
                    profile=str(profiles[i - 1]) if i - 1 < len(profiles) else "",
                    role=str(roles[i - 1]) if i - 1 < len(roles) else "",
                    worker=worker_slots[i - 1][0],
                    glyph=worker_slots[i - 1][1],
                    provider=str(providers[i - 1]) if i - 1 < len(providers) else "",
                    model=str(models[i - 1]) if i - 1 < len(models) else "",
                    parent_id=parent_id,
                    run_id=crew_run,
                    timeout_s=_timeout_for(i),
                    context=str(contexts[i - 1]) if i - 1 < len(contexts) else "",
                    scope=crew_scopes[i - 1] if i - 1 < len(crew_scopes) else None,
                    retryable=retryable,
                )
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._execute_task, task): i for i, task in enumerate(crew, 1)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    results[idx] = {"ok": False, "output": str(e), "quality": "failed"}
                if abort_on_failure and not results[idx].get("ok"):
                    for sib in crew:
                        if sib.status in {"running", "queued"}:
                            self.kill(sib.id)

        succeeded = sum(1 for r in results.values() if r.get("ok"))
        ok = succeeded == len(prompts)
        rows = []
        for i in sorted(results):
            r = results[i]
            label = labels[i - 1] if i - 1 < len(labels) else f"worker-{i}"
            rows.append(
                (
                    label,
                    bool(r.get("ok")),
                    str(r.get("quality") or ("done" if r.get("ok") else "failed")),
                    str(r.get("output") or ""),
                    int(r.get("elapsed_ms") or 0) or None,
                )
            )
        text = _format_sections(f"crew report · {succeeded}/{len(prompts)} succeeded", rows)
        ordered = [results[i] for i in sorted(results)]
        self._emit(
            "orchestrator_end",
            ok=ok,
            total=len(prompts),
            succeeded=succeeded,
            dispatch="sync",
            parent_id=parent_id,
            run_id=crew_run,
            manager=self.manager_view(),
        )
        return {
            "ok": ok,
            "output": text,
            "subagents": len(prompts),
            "succeeded": succeeded,
            "dispatch": "sync",
            "results": ordered,
            "run_id": crew_run,
            "parent_id": parent_id,
            "manager": self.manager_view(),
        }

    def run_parallel_background(
        self,
        prompts: list[str],
        *,
        labels: list[str] | None = None,
        profiles: list[str] | None = None,
        roles: list[str] | None = None,
        providers: list[str] | None = None,
        models: list[str] | None = None,
        parent_id: str = "",
        run_id: str = "",
        timeout_s: float | None = None,
        timeouts: list[float | None] | None = None,
        contexts: list[str] | None = None,
        scope: list[str] | str | None = None,
        scopes: list[list[str] | str | None] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        if not prompts:
            return {"ok": False, "error": "prompts required", "output": "prompts required"}
        if len(prompts) > _MAX_CREW_SIZE:
            msg = f"crew too large ({len(prompts)}); max {_MAX_CREW_SIZE} background workers"
            return {"ok": False, "error": msg, "output": msg}
        budget_error = self._check_spawn_budget(len(prompts))
        if budget_error:
            return {"ok": False, "error": budget_error, "output": budget_error}
        labels = labels or [f"worker-{i}" for i in range(1, len(prompts) + 1)]
        profiles = profiles or [""] * len(prompts)
        roles = roles or [""] * len(prompts)
        providers = providers or [""] * len(prompts)
        models = models or [""] * len(prompts)
        contexts = contexts or [""] * len(prompts)
        crew_scopes = list(scopes) if scopes else [_normalize_scope(scope)] * len(prompts)
        spawned: list[dict[str, Any]] = []
        crew_run = run_id or uuid.uuid4().hex[:8]
        for i, prompt in enumerate(prompts, 1):
            per_timeout = timeouts[i - 1] if timeouts is not None and i - 1 < len(timeouts) else timeout_s
            spawned.append(
                self.run_one_background(
                    str(prompt),
                    label=str(labels[i - 1]),
                    profile=str(profiles[i - 1]) if i - 1 < len(profiles) else "",
                    role=str(roles[i - 1]) if i - 1 < len(roles) else "",
                    provider=str(providers[i - 1]) if i - 1 < len(providers) else "",
                    model=str(models[i - 1]) if i - 1 < len(models) else "",
                    parent_id=parent_id,
                    run_id=crew_run,
                    timeout_s=per_timeout,
                    context=str(contexts[i - 1]) if i - 1 < len(contexts) else "",
                    scope=crew_scopes[i - 1] if i - 1 < len(crew_scopes) else None,
                    retryable=retryable,
                )
            )
            if not spawned[-1].get("background"):
                # Budget (or other) failure mid-crew — stop instead of KeyError on missing job_id.
                partial = [str(s["job_id"]) for s in spawned if s.get("job_id")]
                msg = str(spawned[-1].get("error") or "worker failed to spawn")
                return {
                    "ok": False,
                    "error": msg,
                    "output": msg,
                    "job_ids": partial,
                    "run_id": crew_run,
                    "parent_id": parent_id,
                    "manager": self.manager_view(),
                }
        job_ids: list[str] = [str(s["job_id"]) for s in spawned]
        lines = [f"crew spawned · {len(job_ids)} background workers"]
        for s in spawned:
            lines.append(f"  · {s['job_id']}  {s.get('label', '')}")
        lines.append('When ready: subagent with wait_for: ["id1", "id2", ...] · /agents to monitor')
        return {
            "ok": True,
            "background": True,
            "dispatch": "async",
            "job_ids": job_ids,
            "output": "\n".join(lines),
            "run_id": crew_run,
            "parent_id": parent_id,
            "manager": self.manager_view(),
        }

    def _attach_dispatch_hint(self, out: dict[str, Any], reason: str) -> None:
        hint = dispatch_hint(reason)
        if hint:
            out["dispatch_hint"] = hint
            out["output"] = f"{hint}\n{out.get('output', '')}"

    def _dispatch_wait_for(self, args: dict[str, Any]) -> dict[str, Any] | None:
        wait_for = args.get("wait_for") or args.get("job_ids")
        if not isinstance(wait_for, list) or not wait_for:
            return None
        if args.get("prompt") or args.get("prompts"):
            msg = "wait_for cannot be combined with prompt/prompts — collect existing workers only"
            return {"ok": False, "error": msg, "output": msg}
        timeout = float(args.get("timeout_seconds") or args.get("timeout") or self.timeout_seconds)
        return self.wait_for([str(x) for x in wait_for], timeout_seconds=timeout)

    def _dispatch_crew(
        self,
        prompts: list[Any],
        args: dict[str, Any],
        *,
        background: bool,
        profile: str,
        role: str,
        provider: str,
        model: str,
        dispatch_reason: str,
    ) -> dict[str, Any]:
        n = len(prompts)
        parent_id, run_id = _parent_run(args)
        crew_kwargs = {
            "labels": _label_list(args),
            "profiles": _str_arg_list(args, "profiles") or _repeat_or_none(profile, n),
            "roles": _str_arg_list(args, "roles") or _repeat_or_none(role, n),
            "providers": _str_arg_list(args, "providers") or _repeat_or_none(provider, n),
            "models": _str_arg_list(args, "models") or _repeat_or_none(model, n),
            "parent_id": parent_id,
            "run_id": run_id,
            "timeout_s": _timeout_single(args),
            "timeouts": _timeout_list(args, n),
            "contexts": _str_arg_list(args, "contexts") or _repeat_or_none(str(args.get("context") or ""), n),
            "scopes": _scope_arg_list(args, n),
            "retryable": bool(args.get("retryable", True)),
        }
        if not background:
            crew_kwargs["abort_on_failure"] = _abort_flag(args)
        runner = self.run_parallel_background if background else self.run_parallel
        out = runner([str(p) for p in prompts], **crew_kwargs)
        out["dispatch_reason"] = dispatch_reason
        self._attach_dispatch_hint(out, dispatch_reason)
        return out

    def _dispatch_single(
        self,
        args: dict[str, Any],
        *,
        background: bool,
        profile: str,
        role: str,
        provider: str,
        model: str,
        dispatch_reason: str,
    ) -> dict[str, Any]:
        prompt = _clamp_prompt(str(args.get("prompt") or ""))
        if not prompt:
            msg = "subagent needs prompt (one worker) or prompts (parallel crew)"
            return {"ok": False, "error": msg, "output": msg}
        common = {
            "label": str(args.get("label") or ""),
            "profile": profile,
            "role": role,
            "provider": provider,
            "model": model,
            "parent_id": _parent_run(args)[0],
            "run_id": _parent_run(args)[1],
            "timeout_s": _timeout_single(args),
            "context": str(args.get("context") or ""),
            "scope": _normalize_scope(args.get("scope")),  # type: ignore[arg-type]
            "retryable": bool(args.get("retryable", True)),
        }
        out = self.run_one_background(prompt, **common) if background else self.run_one(prompt, **common)
        out["dispatch"] = "async" if background else "sync"
        out["dispatch_reason"] = dispatch_reason
        self._attach_dispatch_hint(out, dispatch_reason)
        return out

    def dispatch(
        self,
        args: dict[str, Any],
        *,
        parent_id: str = "",
        run_id: str = "",
        abort_on_failure: bool = False,
        depth: int | None = None,
        allow_nested: bool | None = None,
    ) -> dict[str, Any]:
        """Tool entrypoint: prompt(s), optional labels, wait_for, background/wait.

        ``depth`` is this dispatch's nesting level (defaults to the orchestrator's own
        ``depth``); dispatches at ``depth >= _MAX_SUBAGENT_DEPTH`` are blocked unless
        ``allow_nested`` is set. Worker registries never contain the subagent tool, so
        nesting is structurally blocked one level down regardless of this flag.
        """
        collected = self._dispatch_wait_for(args)
        if collected is not None:
            return collected

        eff_depth = self.depth if depth is None else depth
        eff_nested = self.allow_nested if allow_nested is None else allow_nested
        if eff_depth >= _MAX_SUBAGENT_DEPTH and not eff_nested:
            msg = (
                f"nested subagent dispatch blocked (depth {eff_depth} >= {_MAX_SUBAGENT_DEPTH}); "
                "workers cannot spawn their own subagents — pass allow_nested=True to override"
            )
            return {"ok": False, "error": msg, "output": msg}

        background, dispatch_reason = resolve_dispatch_mode(args)
        profile = str(args.get("profile") or "")
        role = str(args.get("role") or "")
        provider = str(args.get("provider") or "")
        model = str(args.get("model") or "")
        if not parent_id:
            parent_id = str(args.get("parent_id") or "")
        if not run_id:
            run_id = str(args.get("run_id") or args.get("parent_run_id") or "")
        if not abort_on_failure:
            abort_on_failure = _abort_flag(args)
        if parent_id or run_id or abort_on_failure:
            args = {**args, "parent_id": parent_id, "run_id": run_id, "abort_on_failure": abort_on_failure}

        prompts = args.get("prompts") or args.get("tasks")
        if isinstance(prompts, list) and prompts:
            return self._dispatch_crew(
                prompts,
                args,
                background=background,
                profile=profile,
                role=role,
                provider=provider,
                model=model,
                dispatch_reason=dispatch_reason,
            )
        return self._dispatch_single(
            args,
            background=background,
            profile=profile,
            role=role,
            provider=provider,
            model=model,
            dispatch_reason=dispatch_reason,
        )

    def kill(self, task_id: str) -> bool:
        for task in self.tasks:
            if task.id == task_id and task.status == "running" and task.cancel is not None:
                task.cancel.request()
                task.status = "killed"
                task.quality = "killed"
                if self.jobs is not None:
                    self.jobs.mark_done(task_id, ok=False, status="killed")
                return True
        return False

    def kill_all(self) -> int:
        running = [t.id for t in self.tasks if t.status == "running" and t.cancel is not None]
        n = 0
        for task_id in running:
            if self.kill(task_id):
                n += 1
        return n
