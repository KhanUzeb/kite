"""Named context checkpoints — full model transcript snapshots for restore/handoff."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from kite.config import ensure_home, kite_home
from kite.context.window import ContextUsage, estimate_usage

CheckpointReason = Literal["manual", "auto", "pre_compact"]


@dataclass
class ContextCheckpoint:
    id: str
    session_id: str
    label: str
    created_at: float
    reason: CheckpointReason
    cwd: str
    messages: list[dict]
    context_usage: dict[str, Any] = field(default_factory=dict)
    todos: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "label": self.label,
            "created_at": self.created_at,
            "reason": self.reason,
            "cwd": self.cwd,
            "messages": self.messages,
            "context_usage": self.context_usage,
            "todos": self.todos,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextCheckpoint:
        return cls(
            id=str(data["id"]),
            session_id=str(data["session_id"]),
            label=str(data.get("label") or ""),
            created_at=float(data.get("created_at") or time.time()),
            reason=str(data.get("reason") or "manual"),  # type: ignore[arg-type]
            cwd=str(data.get("cwd") or ""),
            messages=list(data.get("messages") or []),
            context_usage=dict(data.get("context_usage") or {}),
            todos=list(data.get("todos") or []),
            meta=dict(data.get("meta") or {}),
        )


def checkpoints_dir(session_id: str) -> Path:
    from kite.memory.secure_io import storage_id

    ensure_home()
    root = (kite_home() / "checkpoints").resolve()
    folder = (root / storage_id(session_id, label="session id")).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("invalid session id")
    return folder


def _checkpoint_path(session_id: str, checkpoint_id: str) -> Path:
    from kite.memory.secure_io import storage_id

    name = storage_id(checkpoint_id, label="checkpoint id")
    return checkpoints_dir(session_id) / f"{name}.json"


def make_checkpoint_id() -> str:
    return "cp-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def save_checkpoint(
    *,
    session_id: str,
    messages: list[dict],
    cwd: str,
    label: str = "",
    reason: CheckpointReason = "manual",
    todos: list[dict] | None = None,
    meta: dict[str, Any] | None = None,
    system: str = "",
    tool_schemas: list[dict] | None = None,
    window: int = 128_000,
) -> ContextCheckpoint:
    usage = estimate_usage(system=system, messages=messages, tool_schemas=tool_schemas, window=window)
    cp = ContextCheckpoint(
        id=make_checkpoint_id(),
        session_id=session_id,
        label=label or f"checkpoint {time.strftime('%H:%M:%S')}",
        created_at=time.time(),
        reason=reason,
        cwd=cwd,
        messages=list(messages),
        context_usage={
            "total_tokens": usage.total_tokens,
            "window": usage.window,
            "ratio": round(usage.ratio, 4),
            "remaining": usage.remaining,
        },
        todos=list(todos or []),
        meta=dict(meta or {}),
    )
    folder = checkpoints_dir(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(session_id, cp.id)
    from kite.memory.session_policy import prepare_persisted_value, secure_session_file

    blob = prepare_persisted_value(cp.to_dict())
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    secure_session_file(path)
    _prune_checkpoints(session_id)
    return cp


_MAX_CHECKPOINTS_PER_SESSION = 5


def _prune_checkpoints(session_id: str, keep: int = _MAX_CHECKPOINTS_PER_SESSION) -> None:
    folder = checkpoints_dir(session_id)
    if not folder.is_dir():
        return
    paths = sorted(folder.glob("cp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths[keep:]:
        try:
            path.unlink()
        except OSError:
            pass


def _prefix_matches(folder: Path, checkpoint_id: str) -> list[Path]:
    """Literal prefix scan — checkpoint ids come from CLI/tool input and may
    contain glob metacharacters, so never interpolate them into a glob."""
    prefix = (checkpoint_id or "").strip()
    if not prefix or not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("cp-*.json") if p.name.startswith(prefix))


def load_checkpoint(session_id: str, checkpoint_id: str) -> ContextCheckpoint:
    path = _checkpoint_path(session_id, checkpoint_id)
    if not path.is_file():
        # prefix match
        matches = _prefix_matches(checkpoints_dir(session_id), checkpoint_id)
        if not matches:
            raise FileNotFoundError(f"no checkpoint '{checkpoint_id}' for session {session_id}")
        path = matches[-1]
    return ContextCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_checkpoints(session_id: str, *, limit: int = 20) -> list[ContextCheckpoint]:
    folder = checkpoints_dir(session_id)
    if not folder.is_dir():
        return []
    rows: list[ContextCheckpoint] = []
    for path in sorted(folder.glob("cp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append(ContextCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if len(rows) >= limit:
            break
    return rows


def delete_checkpoint(session_id: str, checkpoint_id: str) -> bool:
    try:
        path = _checkpoint_path(session_id, checkpoint_id)
        if not path.is_file():
            matches = _prefix_matches(checkpoints_dir(session_id), checkpoint_id)
            if not matches:
                return False
            path = matches[-1]
        path.unlink()
        return True
    except OSError:
        return False


def usage_from_checkpoint(cp: ContextCheckpoint) -> ContextUsage | None:
    raw = cp.context_usage
    if not raw:
        return None
    try:
        return ContextUsage(
            total_tokens=int(raw.get("total_tokens") or 0),
            system_tokens=0,
            message_tokens=int(raw.get("total_tokens") or 0),
            tool_tokens=0,
            message_count=len(cp.messages),
            window=int(raw.get("window") or 128_000),
        )
    except (TypeError, ValueError):
        return None
