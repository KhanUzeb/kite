"""Durable notes the agent and user share across sessions (not the JSONL chat log)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kite.config import ensure_home, kite_home
from kite.context.discovery import find_project_root

MemoryScope = Literal["user", "project"]


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    created: float
    scope: MemoryScope

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "created": self.created, "scope": self.scope}

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, default_scope: MemoryScope) -> Note | None:
        text = str(data.get("text") or "").strip()
        if not text:
            return None
        scope = data.get("scope") or default_scope
        if scope not in {"user", "project"}:
            scope = default_scope
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            text=text,
            created=float(data.get("created") or time.time()),
            scope=scope,  # type: ignore[arg-type]
        )


def _read_jsonl(path: Path, *, scope: MemoryScope) -> list[Note]:
    if not path.is_file():
        return []
    notes: list[Note] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        note = Note.from_dict(row, default_scope=scope)
        if note is not None:
            notes.append(note)
    return notes


def _write_jsonl(path: Path, notes: list[Note]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(n.to_dict(), ensure_ascii=False) + "\n" for n in notes)
    path.write_text(body, encoding="utf-8")


def _read_markdown(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class MemoryStore:
    """User-global + project notes. Markdown pin files are included in the prompt."""

    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.root = find_project_root(self.cwd)

    @classmethod
    def open(cls, cwd: str | Path = ".") -> MemoryStore:
        return cls(cwd)

    def user_notes_path(self) -> Path:
        ensure_home()
        return kite_home() / "memory" / "notes.jsonl"

    def project_notes_path(self) -> Path:
        return self.root / ".kite" / "memory" / "notes.jsonl"

    def user_markdown_path(self) -> Path:
        return kite_home() / "memory" / "MEMORY.md"

    def project_markdown_path(self) -> Path:
        return self.root / ".kite" / "MEMORY.md"

    def notes(self, scope: MemoryScope | None = None) -> list[Note]:
        rows: list[Note] = []
        if scope in (None, "user"):
            rows.extend(_read_jsonl(self.user_notes_path(), scope="user"))
        if scope in (None, "project"):
            rows.extend(_read_jsonl(self.project_notes_path(), scope="project"))
        return rows

    def remember(self, text: str, *, scope: MemoryScope = "user") -> Note:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            raise ValueError("empty memory")
        note = Note(id=uuid.uuid4().hex[:8], text=cleaned, created=time.time(), scope=scope)
        path = self.user_notes_path() if scope == "user" else self.project_notes_path()
        existing = _read_jsonl(path, scope=scope)
        existing.append(note)
        _write_jsonl(path, existing)
        return note

    def forget(self, query: str) -> list[Note]:
        q = query.strip().lower()
        if not q:
            return []
        removed: list[Note] = []
        for scope, path in (("user", self.user_notes_path()), ("project", self.project_notes_path())):
            dirty = False
            kept: list[Note] = []
            for note in _read_jsonl(path, scope=scope):  # type: ignore[arg-type]
                if q == note.id.lower() or q in note.text.lower():
                    removed.append(note)
                    dirty = True
                else:
                    kept.append(note)
            if dirty:
                _write_jsonl(path, kept)
        return removed

    def render_for_prompt(self, *, max_chars: int = 4_000) -> str:
        parts: list[str] = []
        pinned = []
        user_md = _read_markdown(self.user_markdown_path())
        if user_md:
            pinned.append(f"### User MEMORY.md\n{user_md}")
        proj_md = _read_markdown(self.project_markdown_path())
        if proj_md:
            pinned.append(f"### Project MEMORY.md\n{proj_md}")
        if pinned:
            parts.append("\n\n".join(pinned))
        notes = self.notes()
        if notes:
            lines = ["### Notes"]
            for note in notes:
                lines.append(f"- ({note.scope}/{note.id}) {note.text}")
            parts.append("\n".join(lines))
        if not parts:
            return ""
        text = "# Memory\nHonor these durable notes. Use the `memory` tool to add or drop them when the user asks.\n\n" + "\n\n".join(
            parts
        )
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text
