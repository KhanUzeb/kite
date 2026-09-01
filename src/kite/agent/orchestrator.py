"""Subagent orchestrator — manager view for parallel LLM workers against a plan."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from dataclasses import dataclass, field
from typing import Any

from kite.agent.events import Event


@dataclass
class SubagentTask:
    id: str
    prompt: str
    label: str
    status: str = "queued"  # queued | running | done | failed
    exit_status: str = ""
    summary: str = ""
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "exit_status": self.exit_status,
            "ok": self.ok,
            "summary": self.summary[:200],
        }


@dataclass
class SubagentOrchestrator:
    """Dispatch bounded nested agent runs; emit manager events for the TUI."""

    runner: Callable[[str], dict[str, Any]]
    on_event: Callable[[Event], None] | None = None
    max_workers: int = 3
    timeout_seconds: int = 300
    tasks: list[SubagentTask] = field(default_factory=list)

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def manager_view(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.tasks]

    def run_one(self, prompt: str, *, label: str = "") -> dict[str, Any]:
        tid = uuid.uuid4().hex[:8]
        title = label or prompt[:60].replace("\n", " ")
        task = SubagentTask(id=tid, prompt=prompt, label=title, status="running")
        self.tasks.append(task)
        self._emit("subagent_start", id=tid, label=title, prompt=prompt[:300], manager=self.manager_view())

        try:
            if self.timeout_seconds > 0:
                from concurrent.futures import Future

                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut: Future[dict[str, Any]] = pool.submit(self.runner, prompt)
                    result = fut.result(timeout=self.timeout_seconds)
            else:
                result = self.runner(prompt)
            submission = str(result.get("submission") or result.get("content") or "")
            status = str(result.get("exit_status") or "done")
            ok = status == "Submitted"
            summary = submission[:4000] if submission else f"exit={status}"
            task.status = "done" if ok else "failed"
            task.exit_status = status
            task.summary = summary
            task.ok = ok
            out = {
                "ok": ok,
                "output": summary,
                "subagent_id": tid,
                "exit_status": status,
                "manager": self.manager_view(),
            }
        except FuturesTimeout:
            task.status = "failed"
            task.summary = f"subagent timed out after {self.timeout_seconds}s"
            task.ok = False
            out = {
                "ok": False,
                "output": task.summary,
                "subagent_id": tid,
                "error": "timeout",
                "manager": self.manager_view(),
            }
        except Exception as e:
            task.status = "failed"
            task.summary = str(e)
            task.ok = False
            out = {"ok": False, "output": str(e), "subagent_id": tid, "error": str(e), "manager": self.manager_view()}

        self._emit(
            "subagent_end",
            id=tid,
            label=title,
            ok=out.get("ok", False),
            preview=str(out.get("output") or "")[:120],
            manager=self.manager_view(),
        )
        return out

    def run_parallel(self, prompts: list[str], *, labels: list[str] | None = None) -> dict[str, Any]:
        if not prompts:
            return {"ok": False, "error": "prompts required", "output": "prompts required"}
        workers = min(self.max_workers, len(prompts))
        labels = labels or [f"worker-{i}" for i in range(1, len(prompts) + 1)]
        sections = [f"orchestrator: {len(prompts)} subagents"]
        results: dict[int, dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.run_one, str(p), label=str(labels[i - 1])): i
                for i, p in enumerate(prompts, 1)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    results[idx] = {"ok": False, "output": str(e)}

        ok = all(r.get("ok") for r in results.values())
        for i in sorted(results):
            r = results[i]
            mark = "✓" if r.get("ok") else "✗"
            sections.append(f"\n--- {mark} {labels[i-1]} ---\n{str(r.get('output') or '')[:2000]}")
        text = "\n".join(sections)
        return {
            "ok": ok,
            "output": text,
            "subagents": len(prompts),
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
