"""Subagent orchestrator — manager view for parallel LLM workers against a plan."""

from __future__ import annotations

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


def worker_glyph(index: int) -> str:
    """Rotate glyphs so parallel workers are easy to spot in the TUI."""
    return _WORKER_GLYPHS[(max(1, index) - 1) % len(_WORKER_GLYPHS)]


def evaluate_subagent_result(result: dict[str, Any]) -> tuple[bool, str, str]:
    """Return (ok, quality, summary). quality: done | partial | failed | killed."""
    if result.get("cancelled"):
        return False, "killed", "cancelled"
    submission = str(result.get("submission") or result.get("content") or "").strip()
    status = str(result.get("exit_status") or "done")
    if status in _SUCCESS_EXIT:
        return True, "done", submission or f"finished ({status})"
    if status in _FAILURE_EXIT:
        return False, "failed", submission or str(result.get("error") or f"failed ({status})")
    if len(submission) >= _MIN_USEFUL_CHARS:
        quality = "done" if status in _USEFUL_EXIT else "partial"
        return True, quality, submission
    if status in _USEFUL_EXIT and submission:
        return True, "partial", submission
    empty = f"finished with {status} (no summary text)" if not submission else submission
    return False, "failed", empty


def _format_sections(
    header: str,
    rows: list[tuple[str, bool, str, str, int | None]],
) -> str:
    lines = [header]
    for label, ok, quality, body, elapsed_ms in rows:
        mark = "✓" if ok else "✗"
        timing = f" · {elapsed_ms}ms" if elapsed_ms else ""
        detail = f" ({quality})" if quality not in {"done", "failed"} else ""
        lines.append(f"\n--- {mark} {label}{detail}{timing} ---\n{body[:_SECTION_LIMIT]}")
    return "\n".join(lines)


@dataclass
class SubagentTask:
    id: str
    prompt: str
    label: str
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
    cancel: CancelToken | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
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


@dataclass
class SubagentOrchestrator:
    """Dispatch bounded nested agent runs; emit manager events for the TUI."""

    runner: Callable[..., dict[str, Any]]
    on_event: Callable[[Event], None] | None = None
    max_workers: int = 3
    timeout_seconds: int = 300
    tasks: list[SubagentTask] = field(default_factory=list)
    jobs: Any | None = None  # JobRegistry | None
    _worker_seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _runner_pool: ThreadPoolExecutor | None = field(default=None, repr=False)

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def _runner_executor(self) -> ThreadPoolExecutor:
        if self._runner_pool is None:
            self._runner_pool = ThreadPoolExecutor(max_workers=max(1, self.max_workers))
        return self._runner_pool

    def manager_view(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.tasks]

    def _task_by_id(self, task_id: str) -> SubagentTask | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def _next_worker(self) -> tuple[int, str]:
        with self._lock:
            self._worker_seq += 1
            return self._worker_seq, worker_glyph(self._worker_seq)

    def _call_runner(self, prompt: str, cancel: CancelToken) -> dict[str, Any]:
        try:
            return self.runner(prompt, cancel=cancel)
        except TypeError:
            return self.runner(prompt)

    def _run_with_timeout(self, prompt: str, cancel: CancelToken) -> dict[str, Any]:
        if self.timeout_seconds <= 0:
            return self._call_runner(prompt, cancel)
        pool = self._runner_executor()
        fut: Future[dict[str, Any]] = pool.submit(self._call_runner, prompt, cancel)
        return fut.result(timeout=self.timeout_seconds)

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
            task.summary = f'"{task.label}" timed out after {self.timeout_seconds}s'
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
        task.summary = summary[:4000] if summary else f"finished ({status})"
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

    def _execute_task(self, task: SubagentTask, prompt: str) -> dict[str, Any]:
        cancel = task.cancel
        assert cancel is not None
        try:
            result = self._run_with_timeout(prompt, cancel)
            if cancel.is_set():
                out = self._finish_task(task, cancelled=True)
            else:
                out = self._finish_task(task, runner_result=result)
        except FuturesTimeout:
            cancel.request()
            out = self._finish_task(task, timed_out=True)
        except Exception as e:
            out = self._finish_task(task, error=str(e))

        self._mark_job_done(task, out)
        self._prune_finished_tasks()
        self._emit(
            "subagent_end",
            id=task.id,
            label=task.label,
            ok=out.get("ok", False),
            quality=out.get("quality", ""),
            preview=str(out.get("output") or "")[:120],
            elapsed_ms=out.get("elapsed_ms", task.elapsed_ms),
            worker=task.worker,
            glyph=task.glyph,
            background=task.background,
            manager=self.manager_view(),
        )
        return out

    def _begin_task(
        self,
        prompt: str,
        *,
        label: str = "",
        worker: int = 0,
        glyph: str = "",
        background: bool = False,
    ) -> SubagentTask:
        tid = uuid.uuid4().hex[:8]
        title = label or prompt[:60].replace("\n", " ")
        if not worker:
            worker, glyph = self._next_worker()
        cancel = CancelToken()
        task = SubagentTask(
            id=tid,
            prompt=prompt,
            label=title,
            status="running",
            cancel=cancel,
            worker=worker,
            glyph=glyph or worker_glyph(worker),
            started_at=time.monotonic(),
            background=background,
        )
        self.tasks.append(task)
        if self.jobs is not None:
            self.jobs.register_subagent(job_id=tid, label=title, prompt=prompt, cancel=cancel)
        self._emit(
            "subagent_start",
            id=tid,
            label=title,
            prompt=prompt[:300],
            worker=worker,
            glyph=task.glyph,
            background=background,
            manager=self.manager_view(),
        )
        return task

    def _run_worker(self, prompt: str, *, label: str, worker: int, glyph: str) -> dict[str, Any]:
        task = self._begin_task(
            prompt,
            label=label,
            worker=worker,
            glyph=glyph,
            background=False,
        )
        return self._execute_task(task, prompt)

    def run_one(
        self,
        prompt: str,
        *,
        label: str = "",
        worker: int = 0,
        glyph: str = "",
    ) -> dict[str, Any]:
        if not worker:
            worker, glyph = self._next_worker()
        return self._run_worker(prompt, label=label or prompt[:60].replace("\n", " "), worker=worker, glyph=glyph)

    def run_one_background(self, prompt: str, *, label: str = "") -> dict[str, Any]:
        task = self._begin_task(prompt, label=label, background=True)

        def _work() -> None:
            self._execute_task(task, prompt)

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

    def run_parallel(self, prompts: list[str], *, labels: list[str] | None = None) -> dict[str, Any]:
        if not prompts:
            return {"ok": False, "error": "prompts required", "output": "prompts required"}
        workers = min(self.max_workers, len(prompts))
        labels = labels or [f"worker-{i}" for i in range(1, len(prompts) + 1)]
        self._emit(
            "orchestrator_start",
            total=len(prompts),
            workers=workers,
            labels=labels[: len(prompts)],
            dispatch="sync",
        )
        results: dict[int, dict[str, Any]] = {}
        worker_slots = [self._next_worker() for _ in prompts]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self._run_worker,
                    str(p),
                    label=str(labels[i - 1]),
                    worker=worker_slots[i - 1][0],
                    glyph=worker_slots[i - 1][1],
                ): i
                for i, p in enumerate(prompts, 1)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    results[idx] = {"ok": False, "output": str(e), "quality": "failed"}

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
        self._emit(
            "orchestrator_end",
            ok=ok,
            total=len(prompts),
            succeeded=succeeded,
            dispatch="sync",
            manager=self.manager_view(),
        )
        return {
            "ok": ok,
            "output": text,
            "subagents": len(prompts),
            "succeeded": succeeded,
            "dispatch": "sync",
            "manager": self.manager_view(),
        }

    def run_parallel_background(self, prompts: list[str], *, labels: list[str] | None = None) -> dict[str, Any]:
        if not prompts:
            return {"ok": False, "error": "prompts required", "output": "prompts required"}
        labels = labels or [f"worker-{i}" for i in range(1, len(prompts) + 1)]
        spawned: list[dict[str, Any]] = []
        for i, prompt in enumerate(prompts, 1):
            spawned.append(self.run_one_background(str(prompt), label=str(labels[i - 1])))
        job_ids = [str(s["job_id"]) for s in spawned]
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
            "manager": self.manager_view(),
        }

    def _attach_dispatch_hint(self, out: dict[str, Any], reason: str) -> None:
        hint = dispatch_hint(reason)
        if hint:
            out["dispatch_hint"] = hint
            out["output"] = f"{hint}\n{out.get('output', '')}"

    def dispatch(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool entrypoint: prompt(s), optional labels, wait_for, background/wait."""
        wait_for = args.get("wait_for") or args.get("job_ids")
        if isinstance(wait_for, list) and wait_for:
            if args.get("prompt") or args.get("prompts"):
                msg = "wait_for cannot be combined with prompt/prompts — collect existing workers only"
                return {"ok": False, "error": msg, "output": msg}
            timeout = float(args.get("timeout_seconds") or args.get("timeout") or self.timeout_seconds)
            return self.wait_for([str(x) for x in wait_for], timeout_seconds=timeout)

        background, dispatch_reason = resolve_dispatch_mode(args)
        prompts = args.get("prompts") or args.get("tasks")
        if isinstance(prompts, list) and prompts:
            labels = args.get("labels")
            if isinstance(labels, list):
                labels = [str(x) for x in labels]
            else:
                labels = None
            if background:
                out = self.run_parallel_background([str(p) for p in prompts], labels=labels)
            else:
                out = self.run_parallel([str(p) for p in prompts], labels=labels)
            out["dispatch_reason"] = dispatch_reason
            self._attach_dispatch_hint(out, dispatch_reason)
            return out

        prompt = str(args.get("prompt") or "")
        if not prompt:
            msg = "subagent needs prompt (one worker) or prompts (parallel crew)"
            return {"ok": False, "error": msg, "output": msg}

        if background:
            out = self.run_one_background(prompt, label=str(args.get("label") or ""))
        else:
            out = self.run_one(prompt, label=str(args.get("label") or ""))
        out["dispatch"] = "async" if background else "sync"
        out["dispatch_reason"] = dispatch_reason
        self._attach_dispatch_hint(out, dispatch_reason)
        return out

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
