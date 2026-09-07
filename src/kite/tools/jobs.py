"""Session-scoped background jobs — bash processes and live LLM subagents."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from kite.agent.cancel import CancelToken
from kite.agent.events import Event
from kite.guardrails.env_filter import filtered_child_env

JobKind = Literal["bash", "subagent"]
JobStatus = Literal["running", "done", "killed", "failed"]

_LOG_RING = 200


@dataclass
class BackgroundJob:
    id: str
    kind: JobKind
    command: str
    cwd: str = ""
    started_at: float = field(default_factory=time.time)
    status: JobStatus = "running"
    pid: int | None = None
    label: str = ""
    proc: subprocess.Popen[str] | None = field(default=None, repr=False)
    cancel: CancelToken | None = field(default=None, repr=False)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_RING), repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def display_label(self, *, width: int = 48) -> str:
        text = (self.label or self.command).replace("\n", " ").strip() or self.id
        if len(text) > width:
            return text[: width - 1] + "…"
        return text

    def append_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)

    def log_text(self) -> str:
        with self._lock:
            return "".join(self.log)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "label": self.label or self.command,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "status": self.status,
            "pid": self.pid,
        }


class JobRegistry:
    """One registry per REPL session (or one-shot `kite run`)."""

    def __init__(
        self,
        *,
        on_event: Callable[[Event], None] | None = None,
        max_log_lines: int = _LOG_RING,
    ) -> None:
        self._jobs: dict[str, BackgroundJob] = {}
        self._lock = threading.RLock()
        self._on_event = on_event
        self._max_log = max_log_lines

    def set_on_event(self, on_event: Callable[[Event], None] | None) -> None:
        self._on_event = on_event

    def _emit(self, event_kind: str, **payload: Any) -> None:
        if self._on_event is None:
            return
        self._on_event(Event(kind=event_kind, payload=payload))  # type: ignore[arg-type]

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def get(self, job_id: str) -> BackgroundJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, *, active_only: bool = True) -> list[BackgroundJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        if active_only:
            jobs = [j for j in jobs if j.status == "running"]
        return sorted(jobs, key=lambda j: j.started_at)

    def active_count(self) -> int:
        return len(self.list(active_only=True))

    def spawn_bash(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 3600.0,
    ) -> BackgroundJob:
        """Start a shell command without waiting; drain stdout into a ring buffer."""
        try:
            from kite.guardrails.sandbox import clamp_cwd, workspace_root

            clamped, reason = clamp_cwd(cwd, workspace_root(cwd), allow_outside=False)
            if clamped is None:
                raise OSError(reason or "cwd escapes sandbox")
            cwd = str(clamped)
        except ImportError:
            pass
        creationflags = 0
        popen_kw: dict[str, Any] = {
            "shell": True,
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env or filtered_child_env({"PAGER": "cat", "GIT_PAGER": "cat"}),
        }
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if creationflags:
                popen_kw["creationflags"] = creationflags
        else:
            popen_kw["preexec_fn"] = os.setsid

        proc = subprocess.Popen(command, **popen_kw)
        job_id = self._new_id()
        job = BackgroundJob(
            id=job_id,
            kind="bash",
            command=command,
            cwd=cwd,
            pid=proc.pid,
            label=command,
            proc=proc,
            log=deque(maxlen=self._max_log),
        )
        with self._lock:
            self._jobs[job_id] = job
        self._emit(
            "job_start",
            id=job_id,
            kind="bash",
            pid=proc.pid,
            command=command,
            label=job.display_label(),
            active=self.active_count(),
        )
        threading.Thread(
            target=self._drain_bash,
            args=(job, timeout_seconds),
            daemon=True,
            name=f"kite-job-{job_id}",
        ).start()
        return job

    def _drain_bash(self, job: BackgroundJob, timeout_seconds: float = 3600.0) -> None:
        proc = job.proc
        if proc is None or proc.stdout is None:
            return
        drained_bytes = 0
        max_bytes = 512_000
        try:
            for line in iter(proc.stdout.readline, ""):
                drained_bytes += len(line.encode("utf-8", errors="replace"))
                job.append_log(line)
                self._emit("job_output", id=job.id, line=line, kind="bash")
                if drained_bytes >= max_bytes:
                    job.append_log("\n...[job output truncated]...\n")
                    break
        except OSError:
            pass
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        rc: int | None = None
        while rc is None and time.monotonic() < deadline:
            try:
                rc = proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                continue
        if rc is None:
            try:
                proc.kill()
            except OSError:
                pass
            rc = -1
            job.append_log("\n...[job killed: timeout]...\n")
        with self._lock:
            if job.status != "running":
                return  # killed already emitted job_end
            job.status = "done" if rc == 0 else "failed"
        self._emit(
            "job_end",
            id=job.id,
            kind="bash",
            ok=rc == 0,
            status=job.status,
            returncode=rc,
            label=job.display_label(),
            active=self.active_count(),
        )

    def register_subagent(
        self,
        *,
        job_id: str | None = None,
        label: str,
        prompt: str = "",
        cancel: CancelToken | None = None,
    ) -> BackgroundJob:
        """Track a live nested LLM worker so /jobs and /kill can reach it."""
        tid = job_id or self._new_id()
        token = cancel or CancelToken()
        job = BackgroundJob(
            id=tid,
            kind="subagent",
            command=prompt or label,
            label=label or (prompt[:60].replace("\n", " ") if prompt else tid),
            cancel=token,
            log=deque(maxlen=self._max_log),
        )
        with self._lock:
            self._jobs[tid] = job
        self._emit(
            "job_start",
            id=tid,
            kind="subagent",
            command=job.command,
            label=job.display_label(),
            active=self.active_count(),
        )
        return job

    def mark_done(
        self,
        job_id: str,
        *,
        ok: bool = True,
        status: JobStatus | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.status = status or ("done" if ok else "failed")
            kind = job.kind
            label = job.display_label()
        self._emit(
            "job_end",
            id=job_id,
            kind=kind,
            ok=ok,
            status=job.status,
            label=label,
            active=self.active_count(),
        )

    def kill(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False
        return self._kill_job(job)

    def kill_all(self) -> int:
        with self._lock:
            running = [j for j in self._jobs.values() if j.status == "running"]
        n = 0
        for job in running:
            if self._kill_job(job):
                n += 1
        return n

    def _kill_job(self, job: BackgroundJob) -> bool:
        # Mark killed before tearing down so the drain thread does not overwrite.
        with self._lock:
            if job.status != "running":
                return False
            job.status = "killed"
        if job.kind == "bash":
            self._kill_bash(job)
        elif job.cancel is not None:
            job.cancel.request()
        self._emit(
            "job_end",
            id=job.id,
            kind=job.kind,
            ok=False,
            status="killed",
            label=job.display_label(),
            active=self.active_count(),
        )
        return True

    def _kill_bash(self, job: BackgroundJob) -> None:
        proc = job.proc
        if proc is None:
            return
        pid = proc.pid
        if sys.platform == "win32" and pid:
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if completed.returncode not in {0, 128, 255}:
                    job.append_log(f"\n...[taskkill exit {completed.returncode}]...\n")
            except (OSError, subprocess.TimeoutExpired):
                pass
            try:
                proc.kill()
            except OSError:
                pass
            return
        # POSIX: terminate the process group started with setsid
        try:
            if pid:
                os.killpg(os.getpgid(pid), 15)  # SIGTERM
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=1.5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                if pid:
                    os.killpg(os.getpgid(pid), 9)  # SIGKILL
            except (OSError, ProcessLookupError):
                try:
                    proc.kill()
                except OSError:
                    pass
