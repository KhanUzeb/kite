"""Episodic memory — what happened, in SQLite (not the chat log)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kite.config import ensure_home, kite_home
from kite.context.discovery import find_project_root

MemoryScope = Literal["user", "project"]

# Anything sqlite3 can raise for a file that is unreadable, not a database, or
# locked by another process, plus OS errors from the path itself (perms,
# missing parents past mkdir). The episodic log is a *cache* of what happened:
# it must never be the reason a durable note or a prompt render fails.
_DB_ERRORS = (sqlite3.Error, OSError)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  created REAL NOT NULL,
  session_id TEXT,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload TEXT,
  cwd TEXT,
  scope TEXT NOT NULL DEFAULT 'user'
);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
"""


@dataclass(frozen=True)
class Episode:
    id: str
    created: float
    session_id: str
    kind: str
    summary: str
    payload: str
    cwd: str
    scope: MemoryScope

    def line(self) -> str:
        return f"{self.scope}/{self.kind}  {self.summary}"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    except Exception:
        # A failed open must not keep the OS handle: on Windows the file stays
        # locked past refcount release, so the quarantiner's replace() would
        # fail with WinError 32 and the corrupt DB could never be moved aside.
        try:
            conn.close()
        except Exception:
            pass
        raise
    return conn


def _quarantine(path: Path) -> None:
    """Move an unreadable DB aside plus its WAL sidecars, with a unique name.

    SQLite keeps `-wal`/`-shm` (`-journal` in rollback mode) next to the main
    file. Moving only the main file leaves a stale WAL behind, and every fresh
    reconnect then tries recovery against it and fails the same way — a sticky
    failure no retry can clear (this is exactly the torn-WAL crash it guards).
    May raise OSError, which the caller turns into "unavailable".
    """
    stem = f"{path.name}.corrupt-{int(time.time())}"
    target = path.with_name(stem)
    n = 0
    while target.exists():
        n += 1
        target = path.with_name(f"{stem}-{n}")
    path.replace(target)
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass


def _connect_or_quarantine(path: Path) -> sqlite3.Connection | None:
    """Open the episode DB, quarantining it if the file is unreadable.

    A corrupt ``episodes.sqlite`` (torn WAL, partial disk write, or a non-sqlite
    file dropped there by something else) used to raise ``DatabaseError`` out of
    every ``remember()`` / ``retrieve_for_prompt()`` / ``render_for_prompt()``
    call — permanently breaking the memory layer over a soft cache. The
    unparseable file is moved aside (preserved, not deleted) and a fresh
    database is created, so the episode log self-heals and durable markdown
    notes keep working.
    """
    try:
        return _connect(path)
    except _DB_ERRORS:
        pass
    try:
        _quarantine(path)
    except OSError:
        return None
    try:
        return _connect(path)
    except _DB_ERRORS:
        return None


def _row(row: sqlite3.Row) -> Episode:
    scope: MemoryScope = "project" if row["scope"] == "project" else "user"
    return Episode(
        id=str(row["id"]),
        created=float(row["created"] or 0),
        session_id=str(row["session_id"] or ""),
        kind=str(row["kind"] or ""),
        summary=str(row["summary"] or ""),
        payload=str(row["payload"] or ""),
        cwd=str(row["cwd"] or ""),
        scope=scope,
    )


class EpisodicStore:
    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.root = find_project_root(self.cwd)

    def user_path(self) -> Path:
        ensure_home()
        return kite_home() / "memory" / "episodes.sqlite"

    def project_path(self) -> Path:
        return self.root / ".kite" / "memory" / "episodes.sqlite"

    def path_for(self, scope: MemoryScope) -> Path:
        return self.user_path() if scope == "user" else self.project_path()

    def record(
        self,
        *,
        kind: str,
        summary: str,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
        scope: MemoryScope = "user",
        cwd: str = "",
    ) -> Episode:
        text = " ".join((summary or "").strip().split())
        if not text:
            raise ValueError("empty episode")
        episode = Episode(
            id=uuid.uuid4().hex[:12],
            created=time.time(),
            session_id=session_id,
            kind=kind.strip() or "event",
            summary=text[:800],
            payload=json.dumps(payload, ensure_ascii=False) if payload else "",
            cwd=cwd or str(self.cwd),
            scope=scope,
        )
        conn = _connect_or_quarantine(self.path_for(scope))
        if conn is None:
            # Unwritable/locked episode log: the episode is a soft cache entry,
            # so skip it rather than failing the caller's durable write.
            raise ValueError("episode log unavailable")
        try:
            conn.execute(
                "INSERT INTO episodes (id, created, session_id, kind, summary, payload, cwd, scope) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode.id,
                    episode.created,
                    episode.session_id,
                    episode.kind,
                    episode.summary,
                    episode.payload,
                    episode.cwd,
                    episode.scope,
                ),
            )
            conn.commit()
        except _DB_ERRORS:
            # Another process may hold the write lock past busy_timeout. Losing an
            # episode row is acceptable; propagating would abort the caller.
            raise ValueError("episode log unavailable") from None
        finally:
            conn.close()
        return episode

    def recent(self, *, limit: int = 20, scope: MemoryScope | None = None) -> list[Episode]:
        rows: list[Episode] = []
        scopes: tuple[MemoryScope, ...] = (scope,) if scope else ("user", "project")
        for sc in scopes:
            path = self.path_for(sc)
            if not path.is_file():
                continue
            conn = _connect_or_quarantine(path)
            if conn is None:
                continue
            try:
                cur = conn.execute(
                    "SELECT * FROM episodes ORDER BY created DESC LIMIT ?",
                    (max(1, limit),),
                )
                rows.extend(_row(r) for r in cur.fetchall())
            except (_DB_ERRORS + (TypeError, ValueError, IndexError, KeyError)):
                continue
            finally:
                conn.close()
        rows.sort(key=lambda e: e.created, reverse=True)
        return rows[: max(1, limit)]

    def forget(self, query: str) -> list[Episode]:
        q = query.strip().lower()
        if not q:
            return []
        removed: list[Episode] = []
        scopes: tuple[MemoryScope, ...] = ("user", "project")
        for scope in scopes:
            path = self.path_for(scope)
            if not path.is_file():
                continue
            conn = _connect_or_quarantine(path)
            if conn is None:
                continue
            try:
                cur = conn.execute("SELECT * FROM episodes")
                hits = [
                    _row(r)
                    for r in cur.fetchall()
                    if q == str(r["id"]).lower() or q in str(r["summary"]).lower()
                ]
                if not hits:
                    continue
                ids = [e.id for e in hits]
                conn.executemany("DELETE FROM episodes WHERE id = ?", [(i,) for i in ids])
                conn.commit()
                removed.extend(hits)
            except (_DB_ERRORS + (TypeError, ValueError, IndexError, KeyError)):
                continue
            finally:
                conn.close()
        return removed

    def render_for_prompt(self, *, limit: int = 8, max_chars: int = 1_200) -> str:
        rows = self.recent(limit=limit)
        if not rows:
            return ""
        lines = ["### Recent episodes"]
        for ep in rows:
            lines.append(f"- ({ep.kind}) {ep.summary}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text
