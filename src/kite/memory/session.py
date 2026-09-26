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
from kite.memory.session_policy import (
    persistence_enabled,
    prepare_persisted_row,
    prepare_persisted_value,
    secure_session_file,
)


def format_meta_line(meta: SessionMeta) -> str:
    """Canonical JSONL meta row — .6f timestamps keep line length stable for in-place patches."""
    task = prepare_persisted_value(meta.task)
    label = prepare_persisted_value(meta.label)
    cwd = prepare_persisted_value(meta.cwd)
    provider = prepare_persisted_value(meta.provider)
    model = prepare_persisted_value(meta.model)
    exit_status = prepare_persisted_value(meta.exit_status)
    reasoning = prepare_persisted_value(meta.reasoning)
    return (
        '{"type":"meta"'
        f',"id":{json.dumps(meta.id)}'
        f',"created_at":{meta.created_at:.6f}'
        f',"updated_at":{meta.updated_at:.6f}'
        f',"cwd":{json.dumps(cwd)}'
        f',"provider":{json.dumps(provider)}'
        f',"model":{json.dumps(model)}'
        f',"task":{json.dumps(task)}'
        f',"label":{json.dumps(label)}'
        f',"exit_status":{json.dumps(exit_status)}'
        f',"reasoning":{json.dumps(reasoning)}'
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
        return _apply_runtime_overlay(meta, path)
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


def session_runtime_overlay(path: Path) -> dict[str, Any]:
    """Runtime identity stamped by note_runtime: provider/model/reasoning/count.

    Empty dict when no sidecar (old sessions) — callers fall back to file meta.
    """
    sidecar = _meta_sidecar(path)
    try:
        row = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(row, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("provider", "model", "reasoning"):
        value = row.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    count = row.get("messages")
    if isinstance(count, int) and count >= 0:
        out["messages"] = count
    return out


def _apply_runtime_overlay(meta: SessionMeta, path: Path) -> SessionMeta:
    overlay = session_runtime_overlay(path)
    for key in ("provider", "model", "reasoning"):
        if key in overlay:
            setattr(meta, key, overlay[key])
    return meta


def _iter_rows_reverse(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSONL rows newest-first without reading the whole file.

    Binary reverse-chunk scan: bounded memory even for hundred-MB transcripts.
    Skips blank/corrupt lines like the forward loader.
    """
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        carry = b""
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            lines = (f.read(step) + carry).split(b"\n")
            carry = lines[0]
            for raw in reversed(lines[1:]):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
        if carry.strip():
            try:
                row = json.loads(carry.decode("utf-8"))
            except ValueError:
                return
            if isinstance(row, dict):
                yield row


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
        "compaction_start",
        "compaction_end",
        "steer",
        "follow_up",
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
    reasoning: str = ""

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
            "reasoning": self.reasoning,
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
            reasoning=str(data.get("reasoning") or ""),
        )


@dataclass
class Session:
    meta: SessionMeta
    messages: list[dict] = field(default_factory=list)
    path: Path | None = None
    # Full message count when messages holds a tail window (load_session_tail);
    # None means messages is complete.
    total_messages: int | None = None

    @property
    def id(self) -> str:
        return self.meta.id

    def note_runtime(self, provider: str = "", model: str = "", reasoning: str = "") -> None:
        """Stamp runtime identity for resume — sidecar only, no transcript rewrite.

        Called at turn end so a later resume restores the last-used
        provider/model/thinking level instead of the creation-time values.
        """
        if provider:
            self.meta.provider = provider
        if model:
            self.meta.model = model
        if reasoning:
            self.meta.reasoning = reasoning
        self.meta.updated_at = time.time()
        if persistence_enabled():
            try:
                self._write_meta_sidecar(self._session_path(), count=len(self.messages))
            except OSError:
                pass

    def append(self, *messages: dict) -> None:
        self.messages.extend(messages)
        self.meta.updated_at = time.time()
        if persistence_enabled():
            self._persist_tail(messages)

    def replace_messages(self, messages: list[dict]) -> None:
        self.messages = list(messages)
        self.meta.updated_at = time.time()
        if persistence_enabled():
            self._persist_compact_snapshot(messages)

    def set_exit(self, status: str) -> None:
        self.meta.exit_status = status
        self.meta.updated_at = time.time()
        if persistence_enabled():
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
                row = {"type": "message", "message": prepare_persisted_value(m)}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        secure_session_file(path)
        self._write_meta_sidecar(path, count=len(self.messages))

    def _persist_tail(self, messages: tuple[dict, ...] | list[dict]) -> None:
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
            return
        with path.open("a", encoding="utf-8") as f:
            for m in messages:
                row = {"type": "message", "message": prepare_persisted_value(m)}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        secure_session_file(path)
        self._touch_meta_timestamp(path, count=len(self.messages))

    def _persist_compact_snapshot(self, messages: list[dict]) -> None:
        """Rewrite session file to current messages — avoids unbounded JSONL growth."""
        self._write_meta()

    def record_context_checkpoint(self, checkpoint_id: str, *, label: str = "", reason: str = "manual") -> None:
        """Append checkpoint metadata to the session audit trail."""
        if not persistence_enabled():
            self.meta.updated_at = time.time()
            return
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
        row = prepare_persisted_row(
            {
                "type": "context_checkpoint",
                "checkpoint_id": checkpoint_id,
                "label": label,
                "reason": reason,
                "updated_at": time.time(),
            }
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        secure_session_file(path)
        self.meta.updated_at = time.time()
        self._touch_meta_timestamp(path, count=len(self.messages))

    def record_event(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Append a durable rollout event — survives crashes between model turns."""
        if kind not in DURABLE_EVENT_KINDS or not persistence_enabled():
            return
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.stat().st_size == 0:
            self._write_meta()
        row = prepare_persisted_row(
            {
                "type": "event",
                "kind": kind,
                "ts": time.time(),
                "payload": payload or {},
            }
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        secure_session_file(path)
        self.meta.updated_at = time.time()
        self._touch_meta_timestamp(path, count=len(self.messages))

    def _write_meta_sidecar(self, path: Path, *, count: int | None = None) -> None:
        side = _meta_sidecar(path)
        data: dict[str, Any] = {"updated_at": self.meta.updated_at}
        if count is not None:
            data["messages"] = count
        for key in ("provider", "model", "reasoning"):
            value = getattr(self.meta, key, "")
            if value:
                data[key] = value
        side.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        secure_session_file(side)

    def _touch_meta_timestamp(self, path: Path, *, count: int | None = None) -> None:
        """Patch updated_at on line 1 — reads only the meta row, not the full transcript."""
        self._write_meta_sidecar(path, count=count)
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
        if persistence_enabled():
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
    from kite.memory.secure_io import storage_id

    folder = sessions_dir().resolve()
    prefix = (session_id or "").strip()
    if not prefix:
        raise FileNotFoundError(f"No session matching '{session_id}'")
    try:
        token = storage_id(prefix, label="session id")
    except ValueError as e:
        raise ValueError(f"invalid session id '{session_id}'") from e
    exact = (folder / f"{token}.jsonl").resolve()
    if not exact.is_relative_to(folder):
        raise ValueError(f"invalid session id '{session_id}'")
    if exact.is_file():
        return exact
    # Literal prefix scan (not a glob): session ids come from tool/CLI input
    # and may contain glob metacharacters like * ? [.
    matches = sorted(
        (p for p in folder.glob("*.jsonl") if p.stem.startswith(token)),
        key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
    )
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


def load_session(session_id: str, *, unique: bool = False) -> Session:
    path = resolve_session_path(session_id, unique=unique)
    meta: SessionMeta | None = None
    messages: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "meta":
                meta = SessionMeta.from_dict(row)
                meta.updated_at = _session_updated_at(path, meta)
                meta = _apply_runtime_overlay(meta, path)
            else:
                messages = _apply_session_row(row, messages)
    if meta is None:
        raise ValueError(f"Session file missing meta: {path}")
    return Session(meta=meta, messages=messages, path=path, total_messages=len(messages))


def load_session_tail(session_id: str, n: int) -> Session:
    """Meta + last N messages without parsing the whole transcript.

    For resume/show display paths on large sessions. A legacy
    ``compact_snapshot`` row inside the window replaces older history, same
    as the forward loader. ``total_messages`` carries the sidecar count when
    known so renderers can note omitted history.
    """
    path = resolve_session_path(session_id)
    _, first_line = _read_first_line_bytes(path)
    row = json.loads(first_line) if first_line.strip() else {}
    if not isinstance(row, dict) or row.get("type") != "meta":
        raise ValueError(f"Session file missing meta: {path}")
    meta = _apply_runtime_overlay(SessionMeta.from_dict(row), path)
    meta.updated_at = _session_updated_at(path, meta)
    total = session_runtime_overlay(path).get("messages")
    want = max(0, int(n))
    collected: list[dict] = []
    if want > 0:
        try:
            for entry in _iter_rows_reverse(path):
                kind = entry.get("type")
                if kind == "compact_snapshot":
                    collected = list(entry.get("messages") or []) + collected
                    break
                if kind == "message":
                    collected.append(entry["message"])
                    if len(collected) >= want:
                        break
        except OSError:
            pass
    collected.reverse()
    return Session(
        meta=meta,
        messages=collected,
        path=path,
        total_messages=int(total) if isinstance(total, int) else None,
    )


def load_session_todos(session_id: str) -> list[dict[str, Any]]:
    """Latest todo snapshot from durable session events (newest-first scan)."""
    try:
        path = resolve_session_path(session_id)
    except (OSError, ValueError, FileNotFoundError):
        return []
    try:
        for row in _iter_rows_reverse(path):
            if row.get("type") != "event" or row.get("kind") != "todo":
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            items = payload.get("items")
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
            continue  # corrupt snapshot — an older one may still be valid
    except OSError:
        return []
    return []


def persist_session_todos(session_id: str, items: list[dict[str, Any]]) -> None:
    """Append a durable todo snapshot for resume after restart."""
    if not session_id:
        return
    try:
        session = load_session(session_id)
    except (OSError, ValueError, FileNotFoundError):
        return
    session.record_event("todo", {"items": items})


def latest_session_for_cwd(cwd: str, *, limit: int = 50) -> SessionMeta | None:
    """Most recently updated session for this workspace, or newest overall."""
    try:
        target = str(Path(cwd or ".").expanduser().resolve())
    except OSError:
        target = cwd or ""
    rows = list_sessions(limit=limit)
    for meta in rows:
        try:
            if str(Path(meta.cwd or ".").expanduser().resolve()) == target:
                return meta
        except OSError:
            if meta.cwd == cwd:
                return meta
    return rows[0] if rows else None


def list_sessions(*, limit: int = 30, query: str = "") -> list[SessionMeta]:
    rows: list[SessionMeta] = []
    for path in sessions_dir().glob("*.jsonl"):
        meta = _read_session_meta(path)
        if meta is not None:
            rows.append(meta)
    rows.sort(key=lambda m: m.updated_at, reverse=True)
    if query:
        from kite.memory.session_format import match_sessions

        rows = match_sessions(rows, query)
    return rows[:limit]


@dataclass(frozen=True)
class DeletedSession:
    id: str
    session: bool
    trajectory: bool


def _trajectory_path(session_id: str) -> Path:
    from kite.memory.secure_io import storage_id

    root = (kite_home() / "trajectories").resolve()
    path = (root / f"{storage_id(session_id, label='session id')}.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("invalid session id")
    return path


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


def prune_sessions(keep: int = 20) -> list[DeletedSession]:
    """Delete oldest sessions, keeping the newest ``keep`` (storage hygiene).

    Never deletes when ``keep`` covers everything. Returns the deleted rows,
    newest-first among the removed.
    """
    keep = max(1, int(keep))
    rows = list_sessions(limit=10_000)
    if len(rows) <= keep:
        return []
    removed: list[DeletedSession] = []
    for meta in rows[keep:]:
        try:
            removed.append(delete_session(meta.id))
        except (OSError, ValueError):
            continue
    return removed


def iter_session_messages(session_id: str) -> Iterator[dict]:
    path = resolve_session_path(session_id)
    messages: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "meta":
                continue
            messages = _apply_session_row(row, messages)
    yield from messages
