"""Import session history from competing coding CLIs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from kite.memory.session import Session, create_session


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_messages(raw_messages: list[Any]) -> list[dict]:
    out: list[dict] = []
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = m.get("content") or ""
        msg: dict[str, Any] = {"role": role, "content": content}
        if m.get("tool_calls"):
            msg["tool_calls"] = m["tool_calls"]
        if m.get("name"):
            msg["name"] = m["name"]
        out.append(msg)
    return out


def import_cursor(path: Path) -> list[dict]:
    """Best-effort import from Cursor agent transcript JSON."""
    data = _read_json(path)
    if isinstance(data, dict):
        if "messages" in data:
            return _normalize_messages(data["messages"])
        if "transcript" in data:
            return _normalize_messages(data["transcript"])
    if isinstance(data, list):
        return _normalize_messages(data)
    raise ValueError("unrecognized Cursor export format")


def import_claude_code(path: Path) -> list[dict]:
    """Import Claude Code JSONL session (one message per line)."""
    messages: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("role"):
            messages.extend(_normalize_messages([row]))
        elif isinstance(row, dict) and "message" in row:
            messages.extend(_normalize_messages([row["message"]]))
    return messages


def import_aider(path: Path) -> list[dict]:
    """Import Aider .aider.chat.history.md — heuristic parse."""
    text = path.read_text(encoding="utf-8", errors="replace")
    messages: list[dict] = []
    current_role = "user"
    buf: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#+\s*(User|Assistant|You)", line, re.I):
            if buf:
                messages.append({"role": current_role, "content": "\n".join(buf).strip()})
                buf = []
            current_role = "assistant" if "assistant" in line.lower() else "user"
        else:
            buf.append(line)
    if buf:
        messages.append({"role": current_role, "content": "\n".join(buf).strip()})
    return _normalize_messages(messages)


def import_codex(path: Path) -> list[dict]:
    data = _read_json(path)
    if isinstance(data, dict) and "messages" in data:
        return _normalize_messages(data["messages"])
    if isinstance(data, list):
        return _normalize_messages(data)
    raise ValueError("unrecognized Codex export format")


IMPORTERS = {
    "cursor": import_cursor,
    "claude": import_claude_code,
    "claude-code": import_claude_code,
    "aider": import_aider,
    "codex": import_codex,
    "kite": lambda p: _normalize_messages(_read_json(p).get("messages", []) if isinstance(_read_json(p), dict) else []),
}


def import_session(format: str, path: Path, *, cwd: str = ".", label: str = "") -> Session:
    fmt = format.lower().strip()
    if fmt not in IMPORTERS:
        known = ", ".join(sorted(IMPORTERS))
        raise ValueError(f"unknown format '{format}'. known: {known}")
    messages = IMPORTERS[fmt](path)
    if not messages:
        raise ValueError("no messages imported")
    session = create_session(
        task=f"imported from {format}: {path.name}",
        cwd=cwd,
        provider="",
        model="",
        label=label or f"import:{fmt}",
    )
    session.replace_messages(messages)
    return session
