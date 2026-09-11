"""Tool executor, process runner, and change journal."""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.agent.exceptions import InterruptAgentFlow
from kite.application.policy import PolicyEngine
from kite.application.tools import PolicyDecision, ToolCall, ToolIntent, ToolResult
from kite.guardrails import redact_secrets
from kite.guardrails.env_filter import filtered_child_env
from kite.guardrails.process import popen_process_group_kwargs, terminate_process_tree

_PASSTHROUGH_KEYS = (
    "returncode",
    "path",
    "diff",
    "submitted",
    "blocked",
    "secrets_redacted",
    "cancelled",
    "directory",
    "items",
    "summary",
)


@dataclass
class ToolExecutor:
    """validate → derive intent → authorize → execute → normalize → redact."""

    policy: PolicyEngine
    runner: Callable[[ToolCall], dict[str, Any]]
    approver: Callable[[ToolIntent, PolicyDecision], bool] | None = None
    redactor: Callable[[str], str] | None = None

    def execute(
        self,
        call: ToolCall,
        run_context: dict[str, Any] | None = None,
        *,
        skip_approval: bool = False,
    ) -> ToolResult:
        run_context = run_context or {}
        intent = self.policy.derive_intent(call)
        decision = self.policy.authorize(intent)
        if not decision.allowed:
            return ToolResult(
                call_id=call.call_id,
                status="denied",
                ok=False,
                error=decision.reason,
                policy_decision=decision,
            )
        if (
            not skip_approval
            and decision.requires_approval
            and self.approver is None
        ):
            return ToolResult(
                call_id=call.call_id,
                status="denied",
                ok=False,
                error="approval required but no approver (headless run)",
                policy_decision=decision,
            )
        if (
            not skip_approval
            and decision.requires_approval
            and self.approver
            and not self.approver(intent, decision)
        ):
            return ToolResult(
                call_id=call.call_id,
                status="denied",
                ok=False,
                error="approval denied",
                policy_decision=decision,
            )
        start = time.monotonic()
        try:
            raw = self.runner(call)
        except InterruptAgentFlow:
            raise
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                status="error",
                ok=False,
                error=str(exc),
                duration=time.monotonic() - start,
                policy_decision=decision,
            )
        output = str(raw.get("output", ""))
        if self.redactor:
            output = self.redactor(output)
        error = str(raw.get("error", ""))
        if self.redactor and error:
            error = self.redactor(error)
        changed = tuple(str(p) for p in raw.get("changed_paths") or ())
        metadata: dict[str, Any] = {"run_context": run_context}
        for key in _PASSTHROUGH_KEYS:
            if key in raw:
                metadata[key] = raw[key]
        return ToolResult(
            call_id=call.call_id,
            status="ok" if raw.get("ok", True) else "error",
            ok=bool(raw.get("ok", True)),
            output=output,
            error=error,
            changed_paths=changed,
            duration=time.monotonic() - start,
            policy_decision=decision,
            metadata=metadata,
        )





@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    truncated: bool = False
    cancelled: bool = False


class ProcessRunner:
    """Cross-platform subprocess runner with timeout and output limits."""

    def __init__(self, *, timeout_seconds: float = 120.0, max_output_bytes: int = 256_000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(self, command: list[str] | str, *, cwd: str | None = None, shell: bool = False) -> ProcessResult:
        env = filtered_child_env()
        start = time.monotonic()
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **popen_process_group_kwargs(),
        )
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            return ProcessResult(-1, stdout or "", stderr or "timeout", time.monotonic() - start)
        except Exception as exc:
            terminate_process_tree(proc)
            return ProcessResult(-1, "", str(exc), time.monotonic() - start)
        stdout, stderr, truncated = stdout or "", stderr or "", False
        if len(stdout.encode()) > self.max_output_bytes:
            stdout = stdout[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        if len(stderr.encode()) > self.max_output_bytes:
            stderr = stderr[: self.max_output_bytes] + "\n...[truncated]"
            truncated = True
        return ProcessResult(int(proc.returncode or 0), stdout, stderr, time.monotonic() - start, truncated)



_MAX_SNAPSHOT_BYTES = 2_000_000


@dataclass
class FileSnapshot:
    path: str
    existed: bool
    content: bytes | None
    mode: int | None
    hash: str


@dataclass
class ChangeRecord:
    path: str
    preimage: FileSnapshot
    postimage_hash: str
    agent_owned: bool = True


@dataclass
class RestoreConflict:
    path: str
    reason: str
    current_hash: str
    expected_hash: str


@dataclass
class ChangeJournal:
    """Track agent mutations for conflict-aware restore."""

    workspace: Path
    records: list[ChangeRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _snapshot(self, path: Path) -> FileSnapshot:
        rel = str(path.relative_to(self.workspace)) if path.is_relative_to(self.workspace) else str(path)
        if not path.exists():
            return FileSnapshot(path=rel, existed=False, content=None, mode=None, hash="")
        data = path.read_bytes()
        if len(data) > _MAX_SNAPSHOT_BYTES:
            data = data[:_MAX_SNAPSHOT_BYTES]
        return FileSnapshot(
            path=rel,
            existed=True,
            content=data,
            mode=path.stat().st_mode,
            hash=self._hash(data),
        )

    def record_write(self, path: str | Path, *, agent_owned: bool = True) -> None:
        with self._lock:
            p = Path(path)
            if not p.is_absolute():
                p = self.workspace / p
            p = p.resolve()
            snap = self._snapshot(p)
            self.records.append(
                ChangeRecord(path=snap.path, preimage=snap, postimage_hash="", agent_owned=agent_owned),
            )

    def record_after_write(self, path: str | Path) -> None:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        post = self._snapshot(p.resolve())
        for rec in reversed(self.records):
            if rec.path == post.path and not rec.postimage_hash:
                rec.postimage_hash = post.hash
                return
        self.record_write(p)
        self.records[-1].postimage_hash = post.hash

    def restore(self) -> tuple[list[str], list[RestoreConflict]]:
        """Restore only unchanged agent-owned files; report conflicts."""
        restored: list[str] = []
        conflicts: list[RestoreConflict] = []
        for rec in reversed(self.records):
            if not rec.agent_owned:
                continue
            target = self.workspace / rec.path
            current = self._snapshot(target) if target.exists() else FileSnapshot(
                path=rec.path, existed=False, content=None, mode=None, hash="",
            )
            if rec.postimage_hash:
                if not current.existed or current.hash != rec.postimage_hash:
                    conflicts.append(
                        RestoreConflict(
                            path=rec.path,
                            reason="user modified after agent write",
                            current_hash=current.hash,
                            expected_hash=rec.postimage_hash,
                        ),
                    )
                    continue
            pre = rec.preimage
            if pre.existed:
                if pre.content is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(pre.content)
                    if pre.mode is not None:
                        try:
                            target.chmod(pre.mode)
                        except OSError:
                            pass
                    restored.append(rec.path)
            elif target.exists():
                try:
                    if not target.resolve().is_relative_to(self.workspace.resolve()):
                        conflicts.append(
                            RestoreConflict(
                                path=rec.path,
                                reason="refusing to delete path outside workspace",
                                current_hash=current.hash,
                                expected_hash=rec.postimage_hash,
                            ),
                        )
                        continue
                except (ValueError, OSError):
                    pass
                target.unlink()
                restored.append(rec.path)
        return restored, conflicts





def build_tool_executor(
    *,
    workspace_root: str | Path,
    execution_mode: str,
    no_guardrails: bool,
    runner: Callable[[ToolCall], dict[str, Any]],
    policy_engine: PolicyEngine | None = None,
) -> ToolExecutor:
    policy = policy_engine or PolicyEngine(
        workspace_root,
        execution_mode=execution_mode,
        no_guardrails=no_guardrails,
    )
    return ToolExecutor(
        policy=policy,
        runner=runner,
        approver=None,
        redactor=lambda text: redact_secrets(text)[0],
    )
