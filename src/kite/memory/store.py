"""Durable memory: markdown semantic facts + SQLite episodes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kite.memory.episodic import Episode, EpisodicStore
from kite.memory.semantic import Note, SemanticStore

MemoryScope = Literal["user", "project"]


@dataclass(frozen=True)
class ForgetResult:
    notes: tuple[Note, ...]
    episodes: tuple[Episode, ...]

    @property
    def total(self) -> int:
        return len(self.notes) + len(self.episodes)


def _migrate_jsonl(semantic: SemanticStore) -> None:
    """Fold legacy notes.jsonl into MEMORY.md once."""
    extra: list[tuple[MemoryScope, Path]] = [
        ("user", semantic.user_path().parent / "notes.jsonl"),
        ("project", semantic.root / ".kite" / "memory" / "notes.jsonl"),
    ]
    seen: set[Path] = set()
    for scope, jsonl in extra:
        path = Path(jsonl)
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        bak = path.with_suffix(".jsonl.bak")
        if bak.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        existing = semantic.notes(scope=scope)
        existing_ids = {n.id for n in existing}
        existing_text = {n.text.lower() for n in existing}
        moved = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            nid = str(row.get("id") or "")
            if nid in existing_ids or text.lower() in existing_text:
                continue
            try:
                semantic.remember(text, scope=scope)
                moved += 1
            except ValueError:
                continue
        if moved or lines:
            try:
                path.replace(bak)
            except OSError:
                pass


class MemoryStore:
    """User-global + project memory. Semantic = markdown; episodic = SQLite."""

    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.semantic = SemanticStore(self.cwd)
        self.episodic = EpisodicStore(self.cwd)
        _migrate_jsonl(self.semantic)

    @classmethod
    def open(cls, cwd: str | Path = ".") -> MemoryStore:
        return cls(cwd)

    def user_notes_path(self) -> Path:
        return self.semantic.user_path()

    def project_notes_path(self) -> Path:
        return self.semantic.project_path()

    def user_markdown_path(self) -> Path:
        return self.semantic.user_path()

    def project_markdown_path(self) -> Path:
        return self.semantic.project_path()

    def notes(self, scope: MemoryScope | None = None) -> list[Note]:
        return self.semantic.notes(scope)

    def episodes(self, *, limit: int = 20, scope: MemoryScope | None = None) -> list[Episode]:
        return self.episodic.recent(limit=limit, scope=scope)

    def remember(self, text: str, *, scope: MemoryScope = "user") -> Note:
        note = self.semantic.remember(text, scope=scope)
        try:
            self.episodic.record(
                kind="remember",
                summary=note.text,
                payload={"id": note.id, "scope": scope},
                scope=scope,
                cwd=str(self.cwd),
            )
        except ValueError:
            pass
        return note

    def forget(self, query: str) -> ForgetResult:
        notes = tuple(self.semantic.forget(query))
        episodes = tuple(self.episodic.forget(query))
        return ForgetResult(notes=notes, episodes=episodes)

    def record_episode(
        self,
        *,
        kind: str,
        summary: str,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
        scope: MemoryScope = "user",
    ) -> Episode | None:
        try:
            return self.episodic.record(
                kind=kind,
                summary=summary,
                session_id=session_id,
                payload=payload,
                scope=scope,
                cwd=str(self.cwd),
            )
        except ValueError:
            return None

    def render_for_prompt(self, *, max_chars: int = 4_000) -> str:
        semantic = self.semantic.render_for_prompt(max_chars=max(800, max_chars - 1_000))
        episodic = self.episodic.render_for_prompt(limit=6, max_chars=900)
        parts = [p for p in (semantic, episodic) if p]
        if not parts:
            return ""
        text = (
            "# Memory\n"
            "Honor durable notes below. Use the `memory` tool to list, remember, or forget.\n\n"
            + "\n\n".join(parts)
        )
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text
