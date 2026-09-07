"""Append-only JSONL session memory (tau session idea, linear-only for now)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.config import ensure_home, kite_home


def format_meta_line(meta: SessionMeta) -> str:
    """Canonical JSONL meta row — .6f timestamps keep line length stable for in-place patches."""
    return (
        '{"type":"meta"'
        f',"id":{json.dumps(meta.id)}'
        f',"created_at":{meta.created_at:.6f}'
        f',"updated_at":{meta.updated_at:.6f}'
        f',"cwd":{json.dumps(meta.cwd)}'
        f',"provider":{json.dumps(meta.provider)}'
        f',"model":{json.dumps(meta.model)}'
        f',"task":{json.dumps(meta.task)}'
        f',"label":{json.dumps(meta.label)}'
        f',"exit_status":{json.dumps(meta.exit_status)}'
        "}"
    )


def _meta_sidecar(path: Path) -> Path:
    return path.with_suffix(".meta")


def _read_first_line_bytes(path: Path) -> tuple[int, str]:
    """Read only the first line — O(meta line), not O(file)."""
    with path.open("rb") as f:
        raw = f.readline()
        if not raw:
            return 0, ""
        if raw.endswith(b"\n"):
            raw = raw[:-1]
        return len(raw), raw.decode("utf-8")


def _read_session_meta(path: Path) -> SessionMeta | None:
    try:
        _, first_line = _read_first_line_bytes(path)
        if not first_line.strip():
            return None
        row = json.loads(first_line)
        if row.get("type") != "meta":
            return None
        meta = SessionMeta.from_dict(row)
        meta.updated_at = _session_updated_at(path, meta)
        return meta
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _session_updated_at(path: Path, meta: SessionMeta) -> float:
    sidecar = _meta_sidecar(path)
    if sidecar.is_file():
        try:
            row = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(row.get("updated_at"), (int, float)):
                return float(row["updated_at"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return meta.updated_at


def sessions_dir() -> Path:
    ensure_home()
    return kite_home() / "sessions"


# Event kinds persisted for crash-safe rollout replay (not re-fed to the model).
DURABLE_EVENT_KINDS = frozenset(
    {
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "tool_start",
        "tool_end",
        "approval",
        "compact",
        "checkpoint",
        "todo",
        "interrupt",
        "subagent_start",
        "subagent_end",
    }
)


@dataclass
class SessionMeta:
    id: str
    created_at: float
    updated_at: float
    cwd: str
    provider: str
    model: str
    task: str
    label: str = ""
    exit_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cwd": self.cwd,
            "provider": self.provider,
            "model": self.model,
            "task": self.task,
            "label": self.label,
            "exit_status": self.exit_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMeta:
        return cls(
            id=str(data["id"]),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            cwd=str(data.get("cwd") or ""),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            task=str(data.get("task") or ""),
            label=str(data.get("label") or ""),
            exit_status=str(data.get("exit_status") or ""),
        )


@dataclass
class Session:
    meta: SessionMeta
    messages: list[dict] = field(default_factory=list)
    path: Path | None = None

    @property
    def id(self) -> str:
        return self.meta.id

    def append(self, *messages: dict) -> None:
        self.messages.extend(messages)
        self.meta.updated_at = time.time()
        self._persist_tail(messages)

    def replace_messages(self, messages: list[dict]) -> None:
        self.messages = list(messages)
        self.meta.updated_at = time.time()
        self._persist_compact_snapshot(messages)

    def set_exit(self, status: str) -> None:
        self.meta.exit_status = status
        self.meta.updated_at = time.time()
        self._write_meta()

    def _session_path(self) -> Path:
        if self.path is None:
            self.path = sessions_dir() / f"{self.meta.id}.jsonl"
        return self.path

    def _write_meta(self) -> None:
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(format_meta_line(self.meta) + "\n")
            for m in self.messages:
                f.write(json.dumps({"type": "message", "message": m}, ensure_ascii=False) + "\n")
        self._write_meta_sidecar(path)

    def _persist_tail(self, messages: tuple[dict, ...] | list[dict]) -> None:
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
            return
        with path.open("a", encoding="utf-8") as f:
            for m in messages:
                f.write(
                    json.dumps({"type": "message", "message": m}, ensure_ascii=False) + "\n"
                )
        self._touch_meta_timestamp(path)

    def _persist_compact_snapshot(self, messages: list[dict]) -> None:
        """Append a compaction snapshot — O(new messages), not O(transcript)."""
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
            return
        row = {
            "type": "compact_snapshot",
            "updated_at": self.meta.updated_at,
            "messages": messages,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._touch_meta_timestamp(path)

    def record_context_checkpoint(self, checkpoint_id: str, *, label: str = "", reason: str = "manual") -> None:
        """Append checkpoint metadata to the session audit trail."""
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
        row = {
            "type": "context_checkpoint",
            "checkpoint_id": checkpoint_id,
            "label": label,
            "reason": reason,
            "updated_at": time.time(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.meta.updated_at = time.time()
        self._touch_meta_timestamp(path)

    def record_event(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Append a durable rollout event — survives crashes between model turns."""
        if kind not in DURABLE_EVENT_KINDS:
            return
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
        row = {
            "type": "event",
            "kind": kind,
            "ts": time.time(),
            "payload": payload or {},
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.meta.updated_at = time.time()
        self._touch_meta_timestamp(path)

    def _write_meta_sidecar(self, path: Path) -> None:
        _meta_sidecar(path).write_text(
            json.dumps({"updated_at": self.meta.updated_at}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _touch_meta_timestamp(self, path: Path) -> None:
        """Patch updated_at on line 1 — reads only the meta row, not the full transcript."""
        self._write_meta_sidecar(path)
        try:
            line_len, old_line = _read_first_line_bytes(path)
            if not old_line.strip():
                return
            row = json.loads(old_line)
            if row.get("type") != "meta":
                return
            new_line = format_meta_line(self.meta)
            new_bytes = new_line.encode("utf-8")
            if len(new_bytes) == line_len:
                with path.open("r+b") as f:
                    f.seek(0)
                    f.write(new_bytes)
                return
            with path.open("rb") as f:
                f.seek(line_len + 1)
                tail = f.read()
            with path.open("wb") as f:
                f.write(new_bytes + b"\n" + tail)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    def save(self) -> Path:
        self._write_meta()
        return self._session_path()


def create_session(
    *,
    task: str,
    cwd: str,
    provider: str,
    model: str,
    label: str = "",
) -> Session:
    now = time.time()
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    meta = SessionMeta(
        id=sid,
        created_at=now,
        updated_at=now,
        cwd=cwd,
        provider=provider,
        model=model,
        task=task,
        label=label or task[:60],
    )
    session = Session(meta=meta)
    session.save()
    return session


def resolve_session_path(session_id: str, *, unique: bool = False) -> Path:
    """Exact id, or a filename prefix. `unique` refuses an ambiguous prefix."""
    folder = sessions_dir()
    exact = folder / f"{session_id}.jsonl"
    if exact.is_file():
        return exact
    matches = sorted(folder.glob(f"{session_id}*.jsonl"))
    if not matches:
        raise FileNotFoundError(f"No session matching '{session_id}'")
    if unique and len(matches) > 1:
        shown = ", ".join(p.stem for p in matches[:8])
        extra = " …" if len(matches) > 8 else ""
        raise ValueError(f"ambiguous session id '{session_id}': {shown}{extra}")
    return matches[-1]


def _apply_session_row(row: dict[str, Any], messages: list[dict]) -> list[dict]:
    if row.get("type") == "compact_snapshot":
        return list(row.get("messages") or [])
    if row.get("type") == "message":
        messages.append(row["message"])
    return messages


def load_session(session_id: str) -> Session:
    path = resolve_session_path(session_id)
    meta: SessionMeta | None = None
    messages: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "meta":
                meta = SessionMeta.from_dict(row)
                meta.updated_at = _session_updated_at(path, meta)
            else:
                messages = _apply_session_row(row, messages)
    if meta is None:
        raise ValueError(f"Session file missing meta: {path}")
    return Session(meta=meta, messages=messages, path=path)


def list_sessions(*, limit: int = 30) -> list[SessionMeta]:
    rows: list[SessionMeta] = []
    for path in sessions_dir().glob("*.jsonl"):
        meta = _read_session_meta(path)
        if meta is not None:
            rows.append(meta)
    rows.sort(key=lambda m: m.updated_at, reverse=True)
    return rows[:limit]


@dataclass(frozen=True)
class DeletedSession:
    id: str
    session: bool
    trajectory: bool


def _trajectory_path(session_id: str) -> Path:
    return kite_home() / "trajectories" / f"{session_id}.json"


def delete_session(session_id: str) -> DeletedSession:
    path = resolve_session_path(session_id, unique=True)
    sid = path.stem
    path.unlink(missing_ok=True)
    _meta_sidecar(path).unlink(missing_ok=True)
    traj = _trajectory_path(sid)
    traj_ok = False
    if traj.is_file():
        traj.unlink()
        traj_ok = True
    return DeletedSession(id=sid, session=True, trajectory=traj_ok)


def delete_all_sessions() -> list[DeletedSession]:
    deleted: list[DeletedSession] = []
    for path in sorted(sessions_dir().glob("*.jsonl")):
        sid = path.stem
        try:
            path.unlink()
            _meta_sidecar(path).unlink(missing_ok=True)
        except OSError:
            continue
        traj = _trajectory_path(sid)
        traj_ok = False
        if traj.is_file():
            try:
                traj.unlink()
                traj_ok = True
            except OSError:
                pass
        deleted.append(DeletedSession(id=sid, session=True, trajectory=traj_ok))
    return deleted


def iter_session_messages(session_id: str) -> Iterator[dict]:
    path = resolve_session_path(session_id)
    messages: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "meta":
                continue
            messages = _apply_session_row(row, messages)
    yield from messages
