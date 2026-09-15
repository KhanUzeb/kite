"""Human-readable session labels for CLI, REPL pickers, and resume hints."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kite.memory.session import SessionMeta


def session_title(meta: SessionMeta, *, max_len: int = 52) -> str:
    text = (meta.label or meta.task or "").strip() or "(untitled)"
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def session_short_id(session_id: str) -> str:
    parts = session_id.split("-")
    if len(parts) >= 3 and parts[-1]:
        return parts[-1]
    return session_id[:12]


def session_status(meta: SessionMeta) -> str:
    return (meta.exit_status or "open").strip() or "open"


def format_session_when(ts: float, *, now: float | None = None) -> tuple[str, str, str]:
    """Return (date, time, relative) for a unix timestamp."""
    now = now if now is not None else time.time()
    dt = datetime.fromtimestamp(ts)
    date_s = dt.strftime("%Y-%m-%d")
    time_s = dt.strftime("%H:%M")
    delta = max(0.0, now - ts)
    if delta < 60:
        rel = "just now"
    elif delta < 3600:
        rel = f"{int(delta // 60)}m ago"
    elif delta < 86400:
        rel = f"{int(delta // 3600)}h ago"
    elif delta < 172800:
        rel = "yesterday"
    elif delta < 604800:
        rel = f"{int(delta // 86400)}d ago"
    else:
        rel = date_s
    return date_s, time_s, rel


def format_session_picker_label(meta: SessionMeta, *, current: str | None = None) -> str:
    date_s, time_s, rel = format_session_when(meta.updated_at)
    title = session_title(meta, max_len=44)
    status = session_status(meta)
    model = f"{meta.provider}/{meta.model}".strip("/") or "—"
    cwd = Path(meta.cwd).name if meta.cwd else ""
    bits = [f"{date_s} {time_s}", title, f"[{status}]", model]
    if cwd:
        bits.append(f"· {cwd}")
    bits.append(f"({session_short_id(meta.id)})")
    row = "  ".join(bits)
    if rel not in {date_s, "just now"} and rel not in row:
        row += f"  · {rel}"
    if current and meta.id == current:
        row += "  *"
    return row


def format_session_resume_hint(meta: SessionMeta) -> str:
    date_s, time_s, _ = format_session_when(meta.updated_at)
    title = session_title(meta)
    model = f"{meta.provider}/{meta.model}".strip("/") or "—"
    return f"{date_s} {time_s}  ·  {title}  ·  {model}  ·  {session_short_id(meta.id)}"


def match_sessions(rows: list[SessionMeta], query: str) -> list[SessionMeta]:
    q = (query or "").strip().lower()
    if not q:
        return list(rows)
    matched: list[SessionMeta] = []
    for meta in rows:
        date_s, time_s, _ = format_session_when(meta.updated_at)
        haystack = " ".join(
            (
                meta.id,
                session_short_id(meta.id),
                meta.label,
                meta.task,
                meta.cwd,
                Path(meta.cwd).name if meta.cwd else "",
                meta.provider,
                meta.model,
                meta.exit_status,
                date_s,
                time_s,
            )
        ).lower()
        if q in haystack or meta.id.startswith(q):
            matched.append(meta)
    return matched


def suggest_sessions(query: str, *, limit: int = 5) -> list[SessionMeta]:
    from kite.memory.session import list_sessions

    rows = list_sessions(limit=500)
    q = (query or "").strip().lower()
    if not q:
        return rows[:limit]
    prefix = [m for m in rows if m.id.startswith(q)]
    if prefix:
        return prefix[:limit]
    fuzzy = match_sessions(rows, q)
    return fuzzy[:limit]


def session_pick_items(
    rows: list[SessionMeta],
    *,
    current: str | None = None,
) -> list[tuple[str, str]]:
    return [(meta.id, format_session_picker_label(meta, current=current)) for meta in rows]


def _transcript_text(content: Any) -> str:
    """Normalize persisted message content (str | list | None) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                text = part.get("text") if isinstance(part.get("text"), str) else None
                if text is not None:
                    bits.append(text)
                else:
                    bits.append(str(part))
            else:
                bits.append(str(part))
        return "".join(bits)
    return str(content)


def _tool_call_lines(message: dict[str, Any]) -> list[str]:
    """Human-readable tool call summaries from tool_calls, falling back to extra.actions."""
    lines: list[str] = []
    seen: set[str] = set()
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or tc.get("name") or "tool")
        call_id = str(tc.get("id") or "")
        args = str(fn.get("arguments") or tc.get("arguments") or "").strip()
        if len(args) > 120:
            args = args[:117] + "…"
        line = f"{name}({args})" if args else name
        if call_id:
            line += f" [{call_id}]"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
    actions = extra.get("actions") if isinstance(extra, dict) else None
    if not lines and isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = str(action.get("tool") or "tool")
            call_id = str(action.get("id") or "")
            args = str(action.get("arguments") or "").strip()
            if len(args) > 120:
                args = args[:117] + "…"
            line = f"{name}({args})" if args and len(args) < 120 else name
            if call_id:
                line += f" [{call_id}]"
            if line not in seen:
                seen.add(line)
                lines.append(line)
    return lines


def transcript_entries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological transcript rows covering user/assistant/tool/system/exit kinds.

    Pure data helper — rendering lives in kite.ui.render so the memory layer stays UI-free.
    Every persisted message yields exactly one entry, preserving file order.
    """
    entries: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            entries.append({"index": index, "kind": "unknown", "label": "message", "body": str(message)})
            continue
        role = str(message.get("role") or "unknown")
        extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
        body = _transcript_text(message.get("content"))
        if role == "exit":
            status = str(extra.get("exit_status") or body or "exit").strip() or "exit"
            submission = str(extra.get("submission") or "").strip()
            shown = submission or body
            entries.append(
                {
                    "index": index,
                    "kind": "exit",
                    "label": f"exit:{status}",
                    "body": shown,
                    "status": status,
                    "submission": submission,
                }
            )
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or extra.get("id") or "").strip()
            label = f"tool result [{call_id}]" if call_id else "tool result"
            entries.append({"index": index, "kind": "tool", "label": label, "body": body or "—"})
        elif role == "assistant":
            calls = _tool_call_lines(message)
            entries.append(
                {"index": index, "kind": "assistant", "label": "assistant", "body": body, "tool_calls": calls}
            )
        elif role == "user":
            label = "tool result" if body.lstrip().startswith("<tool_result") else "user"
            kind = "tool" if label == "tool result" else "user"
            entries.append({"index": index, "kind": kind, "label": label, "body": body or "—"})
        elif role == "system":
            entries.append({"index": index, "kind": "system", "label": "system", "body": body or "—"})
        else:
            entries.append({"index": index, "kind": "unknown", "label": role, "body": body or "—"})
    return entries


def render_sessions_table(
    console: Any,
    rows: list[SessionMeta],
    *,
    title: str,
    current: str | None = None,
) -> None:
    """Deprecated re-export — canonical home is :func:`kite.ui.tables.render_sessions_table`."""
    from kite.ui.tables import render_sessions_table as _render

    _render(console, rows, title=title, current=current)
