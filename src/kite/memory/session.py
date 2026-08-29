"""Append-only JSONL session memory (tau session idea, linear-only for now)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from kite.config import ensure_home, kite_home


def sessions_dir() -> Path:
    ensure_home()
    return kite_home() / "sessions"


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
        self.save()

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
        # Rewrite file: meta line + all messages (simple & durable enough for slim harness)
        lines = [json.dumps({"type": "meta", **self.meta.to_dict()}, ensure_ascii=False)]
        for m in self.messages:
            lines.append(json.dumps({"type": "message", "message": m}, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

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


def load_session(session_id: str) -> Session:
    path = resolve_session_path(session_id)
    meta: SessionMeta | None = None
    messages: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") == "meta":
            meta = SessionMeta.from_dict(row)
        elif row.get("type") == "message":
            messages.append(row["message"])
    if meta is None:
        raise ValueError(f"Session file missing meta: {path}")
    return Session(meta=meta, messages=messages, path=path)


def list_sessions(*, limit: int = 30) -> list[SessionMeta]:
    rows: list[SessionMeta] = []
    for path in sorted(sessions_dir().glob("*.jsonl"), reverse=True):
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            row = json.loads(first)
            if row.get("type") == "meta":
                rows.append(SessionMeta.from_dict(row))
        except (OSError, json.JSONDecodeError, IndexError, KeyError, ValueError):
            continue
        if len(rows) >= limit:
            break
    return rows


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
    path.unlink()
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
    session = load_session(session_id)
    yield from session.messages
