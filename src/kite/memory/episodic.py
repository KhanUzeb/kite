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
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _row(row: sqlite3.Row) -> Episode:
    scope = row["scope"] if row["scope"] in {"user", "project"} else "user"
    return Episode(
        id=str(row["id"]),
        created=float(row["created"] or 0),
        session_id=str(row["session_id"] or ""),
        kind=str(row["kind"] or ""),
        summary=str(row["summary"] or ""),
        payload=str(row["payload"] or ""),
        cwd=str(row["cwd"] or ""),
        scope=scope,  # type: ignore[arg-type]
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
        conn = _connect(self.path_for(scope))
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
            conn = _connect(path)
            try:
                cur = conn.execute(
                    "SELECT * FROM episodes ORDER BY created DESC LIMIT ?",
                    (max(1, limit),),
                )
                rows.extend(_row(r) for r in cur.fetchall())
            finally:
                conn.close()
        rows.sort(key=lambda e: e.created, reverse=True)
        return rows[: max(1, limit)]

    def forget(self, query: str) -> list[Episode]:
        q = query.strip().lower()
        if not q:
            return []
        removed: list[Episode] = []
        for scope in ("user", "project"):
            path = self.path_for(scope)  # type: ignore[arg-type]
            if not path.is_file():
                continue
            conn = _connect(path)
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
