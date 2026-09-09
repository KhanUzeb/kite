"""Subagent orchestrator — manager view for parallel LLM workers against a plan."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any

from kite.agent.cancel import CancelToken
from kite.agent.events import Event

_SUCCESS_EXIT = frozenset({"Submitted"})
_USEFUL_EXIT = frozenset({"LimitsExceeded", "Stalled"})
_FAILURE_EXIT = frozenset({"Error", "ProviderFault", "Interrupted"})
_WORKER_GLYPHS = ("◆", "●", "◇", "▲", "▶", "★")


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
        return True, "done", submission or f"exit={status}"
    if status in _FAILURE_EXIT:
        return False, "failed", submission or str(result.get("error") or f"exit={status}")
    if len(submission) >= 40:
        quality = "done" if status in _USEFUL_EXIT else "partial"
        return True, quality, submission
    if status in _USEFUL_EXIT and submission:
        return True, "partial", submission
    return False, "failed", submission or f"exit={status}"


@dataclass
class SubagentTask:
    id: str
    prompt: str
    label: str
    status: str = "queued"  # queued | running | done | partial | failed | killed
    exit_status: str = ""
    summary: str = ""
    ok: bool = False
    quality: str = ""
    worker: int = 0
    glyph: str = "◆"
    started_at: float = 0.0
    elapsed_ms: int = 0
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

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def manager_view(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.tasks]

    def _next_worker(self) -> tuple[int, str]:
        self._worker_seq += 1
        return self._worker_seq, worker_glyph(self._worker_seq)

    def _call_runner(self, prompt: str, cancel: CancelToken) -> dict[str, Any]:
        try:
            return self.runner(prompt, cancel=cancel)
        except TypeError:
            return self.runner(prompt)

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
            return {
                "ok": False,
                "output": "cancelled",
                "subagent_id": task.id,
                "error": "cancelled",
                "cancelled": True,
                "quality": "killed",
                "elapsed_ms": task.elapsed_ms,
                "manager": self.manager_view(),
            }

        if timed_out:
            task.status = "failed"
            task.quality = "failed"
            task.summary = f"subagent timed out after {self.timeout_seconds}s"
            task.ok = False
            return {
                "ok": False,
                "output": task.summary,
                "subagent_id": task.id,
                "error": "timeout",
                "quality": "failed",
                "elapsed_ms": task.elapsed_ms,
                "manager": self.manager_view(),
            }

        if error:
            task.status = "failed"
            task.quality = "failed"
            task.summary = error
            task.ok = False
            return {
                "ok": False,
                "output": error,
                "subagent_id": task.id,
                "error": error,
                "quality": "failed",
                "elapsed_ms": task.elapsed_ms,
                "manager": self.manager_view(),
            }

        result = runner_result or {}
        ok, quality, summary = evaluate_subagent_result(result)
        status = str(result.get("exit_status") or "done")
        task.exit_status = status
        task.summary = summary[:4000] if summary else f"exit={status}"
        task.quality = quality
        task.ok = ok
        task.status = quality if ok else "failed"
        return {
            "ok": ok,
            "output": task.summary,
            "subagent_id": task.id,
            "exit_status": status,
            "quality": quality,
            "elapsed_ms": task.elapsed_ms,
            "manager": self.manager_view(),
        }

    def run_one(self, prompt: str, *, label: str = "", worker: int = 0, glyph: str = "") -> dict[str, Any]:
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
            manager=self.manager_view(),
        )

        try:
            if self.timeout_seconds > 0:
                from concurrent.futures import Future

                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut: Future[dict[str, Any]] = pool.submit(self._call_runner, prompt, cancel)
                    result = fut.result(timeout=self.timeout_seconds)
            else:
                result = self._call_runner(prompt, cancel)
            if cancel.is_set():
                out = self._finish_task(task, cancelled=True)
            else:
                out = self._finish_task(task, runner_result=result)
        except FuturesTimeout:
            cancel.request()
            out = self._finish_task(task, timed_out=True)
        except Exception as e:
            out = self._finish_task(task, error=str(e))

        if self.jobs is not None:
            existing = self.jobs.get(tid)
            if existing is not None and existing.status == "running":
                self.jobs.mark_done(tid, ok=bool(out.get("ok")), status="killed" if cancel.is_set() else None)

        self._emit(
            "subagent_end",
            id=tid,
            label=title,
            ok=out.get("ok", False),
            quality=out.get("quality", ""),
            preview=str(out.get("output") or "")[:120],
            elapsed_ms=out.get("elapsed_ms", task.elapsed_ms),
            worker=worker,
            glyph=task.glyph,
            manager=self.manager_view(),
        )
        return out

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
        )
        results: dict[int, dict[str, Any]] = {}
        worker_slots = [self._next_worker() for _ in prompts]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self.run_one,
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

        ok_count = sum(1 for r in results.values() if r.get("ok"))
        ok = ok_count == len(prompts)
        sections = [f"crew report · {ok_count}/{len(prompts)} workers delivered"]
        for i in sorted(results):
            r = results[i]
            quality = str(r.get("quality") or ("done" if r.get("ok") else "failed"))
            mark = "✓" if r.get("ok") else "✗"
            label = labels[i - 1] if i - 1 < len(labels) else f"worker-{i}"
            elapsed = r.get("elapsed_ms")
            timing = f" · {elapsed}ms" if elapsed else ""
            sections.append(f"\n--- {mark} {label} ({quality}){timing} ---\n{str(r.get('output') or '')[:2000]}")
        text = "\n".join(sections)
        self._emit(
            "orchestrator_end",
            ok=ok,
            total=len(prompts),
            delivered=ok_count,
            manager=self.manager_view(),
        )
        return {
            "ok": ok,
            "output": text,
            "subagents": len(prompts),
            "delivered": ok_count,
            "manager": self.manager_view(),
        }

    def dispatch(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool entrypoint: `prompt` or `prompts` (+ optional `labels`)."""
        prompts = args.get("prompts") or args.get("tasks")
        if isinstance(prompts, list) and prompts:
            labels = args.get("labels")
            if isinstance(labels, list):
                labels = [str(x) for x in labels]
            else:
                labels = None
            return self.run_parallel([str(p) for p in prompts], labels=labels)
        prompt = str(args.get("prompt") or "")
        if not prompt:
            return {"ok": False, "error": "prompt or prompts required", "output": "prompt or prompts required"}
        return self.run_one(prompt, label=str(args.get("label") or ""))

    def kill(self, task_id: str) -> bool:
        for task in self.tasks:
            if task.id == task_id and task.status == "running" and task.cancel is not None:
                task.cancel.request()
                task.status = "killed"
                if self.jobs is not None:
                    self.jobs.mark_done(task_id, ok=False, status="killed")
                return True
        return False

    def kill_all(self) -> int:
        n = 0
        for task in self.tasks:
            if task.status == "running" and task.cancel is not None:
                task.cancel.request()
                task.status = "killed"
                n += 1
        return n
