"""Semantic memory — durable facts in markdown (user + project MEMORY.md)."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kite.config import ensure_home, kite_home
from kite.context.discovery import find_project_root

MemoryScope = Literal["user", "project"]

NOTE_RE = re.compile(
    r"^-\s+\[`?(?P<id>[a-zA-Z0-9_-]{4,16})`?\]\s+(?P<text>.+?)\s*$"
)

HEADER = """# Semantic memory

Durable facts and preferences. Edit this file, or use `/remember`.

## Notes
"""


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    created: float
    scope: MemoryScope

    def bullet(self) -> str:
        return f"- [`{self.id}`] {self.text}"


def _split_notes(raw: str) -> tuple[str, str]:
    """Return (pin text, notes section body)."""
    text = raw.replace("\r\n", "\n")
    marker = re.search(r"(?im)^##\s+notes\s*$", text)
    if not marker:
        return text.strip(), ""
    pin = text[: marker.start()].strip()
    body = text[marker.end() :].lstrip("\n")
    return pin, body


def parse_notes(raw: str, *, scope: MemoryScope) -> list[Note]:
    _, body = _split_notes(raw)
    notes: list[Note] = []
    for line in body.splitlines():
        match = NOTE_RE.match(line.strip())
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        notes.append(
            Note(id=match.group("id"), text=text, created=0.0, scope=scope)
        )
    return notes


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    path.write_text(body, encoding="utf-8")


def render_file(pin: str, notes: list[Note]) -> str:
    pin_text = pin.strip() or "# Semantic memory\n\nDurable facts and preferences. Edit this file, or use `/remember`."
    if not re.search(r"(?im)^##\s+notes\s*$", pin_text):
        parts = [pin_text, "", "## Notes"]
    else:
        parts = [pin_text]
    if notes:
        parts.append("")
        parts.extend(n.bullet() for n in notes)
    else:
        parts.append("")
    return "\n".join(parts).strip() + "\n"


class SemanticStore:
    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.root = find_project_root(self.cwd)

    def user_path(self) -> Path:
        ensure_home()
        return kite_home() / "memory" / "MEMORY.md"

    def project_path(self) -> Path:
        return self.root / ".kite" / "MEMORY.md"

    def path_for(self, scope: MemoryScope) -> Path:
        return self.user_path() if scope == "user" else self.project_path()

    def pin_text(self, scope: MemoryScope | None = None) -> str:
        parts: list[str] = []
        if scope in (None, "user"):
            pin, _ = _split_notes(_read(self.user_path()))
            if pin:
                parts.append(pin)
        if scope in (None, "project"):
            pin, _ = _split_notes(_read(self.project_path()))
            if pin:
                parts.append(pin)
        return "\n\n".join(parts).strip()

    def notes(self, scope: MemoryScope | None = None) -> list[Note]:
        rows: list[Note] = []
        if scope in (None, "user"):
            rows.extend(parse_notes(_read(self.user_path()), scope="user"))
        if scope in (None, "project"):
            rows.extend(parse_notes(_read(self.project_path()), scope="project"))
        return rows

    def remember(self, text: str, *, scope: MemoryScope = "user") -> Note:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            raise ValueError("empty memory")
        note = Note(id=uuid.uuid4().hex[:8], text=cleaned, created=time.time(), scope=scope)
        path = self.path_for(scope)
        raw = _read(path)
        pin, _ = _split_notes(raw) if raw.strip() else (HEADER.rsplit("## Notes", 1)[0].strip(), "")
        existing = parse_notes(raw, scope=scope)
        existing.append(note)
        _write(path, render_file(pin or HEADER.rsplit("## Notes", 1)[0].strip(), existing))
        return note

    def forget(self, query: str) -> list[Note]:
        q = query.strip().lower()
        if not q:
            return []
        removed: list[Note] = []
        scopes: tuple[MemoryScope, ...] = ("user", "project")
        for scope in scopes:
            path = self.path_for(scope)
            raw = _read(path)
            if not raw.strip():
                continue
            pin, _ = _split_notes(raw)
            kept: list[Note] = []
            dirty = False
            for note in parse_notes(raw, scope=scope):
                if q == note.id.lower() or q in note.text.lower():
                    removed.append(note)
                    dirty = True
                else:
                    kept.append(note)
            if dirty:
                _write(path, render_file(pin, kept))
        return removed

    def render_for_prompt(self, *, max_chars: int = 3_500) -> str:
        parts: list[str] = []
        user_pin, _ = _split_notes(_read(self.user_path()))
        if user_pin:
            parts.append(f"### User MEMORY.md\n{user_pin}")
        proj_pin, _ = _split_notes(_read(self.project_path()))
        if proj_pin:
            parts.append(f"### Project MEMORY.md\n{proj_pin}")
        notes = self.notes()
        if notes:
            lines = ["### Notes"]
            for note in notes:
                lines.append(f"- ({note.scope}/{note.id}) {note.text}")
            parts.append("\n".join(lines))
        if not parts:
            return ""
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n\n...[truncated]..."
        return text
