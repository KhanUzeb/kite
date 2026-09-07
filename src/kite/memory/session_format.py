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


def render_sessions_table(
    console: Any,
    rows: list[SessionMeta],
    *,
    title: str,
    current: str | None = None,
) -> None:
    from rich.table import Table

    table = Table(title=title, show_lines=False, pad_edge=False)
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Title", overflow="ellipsis", max_width=36)
    table.add_column("Model", style="cyan", no_wrap=True, max_width=22)
    table.add_column("Status", no_wrap=True)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Dir", style="dim", no_wrap=True, max_width=14)

    for meta in rows:
        date_s, time_s, rel = format_session_when(meta.updated_at)
        mark = " *" if current and meta.id == current else ""
        status = session_status(meta)
        status_style = "green" if status == "Submitted" else ("yellow" if status == "open" else "dim")
        cwd = Path(meta.cwd).name if meta.cwd else "—"
        table.add_row(
            date_s,
            time_s,
            session_title(meta, max_len=34) + mark,
            f"{meta.provider}/{meta.model}".strip("/") or "—",
            f"[{status_style}]{status}[/]",
            session_short_id(meta.id),
            cwd,
        )
    console.print(table)
    if rows:
        console.print(
            f"[dim]resume:[/] [bold]kite resume <id>[/]  "
            f"[dim]· filter:[/] kite sessions -q text  "
            f"[dim]· show:[/] kite sessions --show {rows[0].id}"
        )
