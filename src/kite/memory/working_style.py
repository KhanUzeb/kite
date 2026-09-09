"""Fluid long-term awareness of how the user tends to work — soft context, not rules."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kite.config import ensure_home, kite_home

if TYPE_CHECKING:
    from kite.memory.store import MemoryStore

_SIGNALS_MARKER = re.compile(r"(?im)^##\s+signals\s*$")
_SIGNAL_LINE = re.compile(r"^-\s+(?P<text>.+?)\s*$")

_DEFAULT_PIN = """# Working rhythm

How you tend to work — soft context for Kite, not rigid rules. Edit freely.
Kite also appends gentle observations from past sessions under Signals.
"""

_MAX_SIGNALS = 10
_MAX_EPISODE_SIGNALS = 4


def working_path() -> Path:
    ensure_home()
    return kite_home() / "memory" / "WORKING.md"


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    from kite.memory.secure_io import secure_memory_write

    path.parent.mkdir(parents=True, exist_ok=True)
    secure_memory_write(path, text)


def _split_signals(raw: str) -> tuple[str, list[str]]:
    text = raw.replace("\r\n", "\n")
    marker = _SIGNALS_MARKER.search(text)
    if not marker:
        return text.strip(), []
    pin = text[: marker.start()].strip()
    signals: list[str] = []
    for line in text[marker.end() :].splitlines():
        match = _SIGNAL_LINE.match(line.strip())
        if match:
            item = match.group("text").strip()
            if item:
                signals.append(item)
    return pin, signals


def _render_file(pin: str, signals: list[str]) -> str:
    body = pin.strip() or _DEFAULT_PIN.strip()
    if not _SIGNALS_MARKER.search(body):
        parts = [body, "", "## Signals"]
    else:
        parts = [body]
    if signals:
        parts.append("")
        parts.extend(f"- {s}" for s in signals)
    else:
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def read_narrative() -> str:
    pin, _ = _split_signals(_read(working_path()))
    return pin


def read_signals() -> list[str]:
    _, signals = _split_signals(_read(working_path()))
    return signals


def append_signal(text: str) -> str:
    from kite.memory.secure_io import MAX_SIGNAL_CHARS, clamp_memory_text

    cleaned = clamp_memory_text(text, max_chars=MAX_SIGNAL_CHARS)
    path = working_path()
    raw = _read(path)
    pin, signals = _split_signals(raw) if raw.strip() else (_DEFAULT_PIN.strip(), [])
    needle = cleaned.lower()
    if any(s.lower() == needle for s in signals):
        return cleaned
    signals = [cleaned] + [s for s in signals if s.lower() != needle]
    signals = signals[:_MAX_SIGNALS]
    _write(path, _render_file(pin, signals))
    return cleaned


def _normalize_signal(text: str) -> str:
    return " ".join(text.strip().split())[:200]


def _signal_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())[:48]


def infer_style_signals(
    *,
    mode: str = "",
    approval: str = "",
    tool_calls: int = 0,
    write_edits: int = 0,
    bash_calls: int = 0,
    compaction_count: int = 0,
    subagent_runs: int = 0,
    interrupted: bool = False,
    exit_status: str = "",
) -> list[str]:
    """Heuristic, non-weighted observations from one turn — phrased softly."""
    out: list[str] = []
    mode_l = (mode or "").strip().lower()
    approval_l = (approval or "").strip().lower()

    if mode_l == "plan":
        out.append("often sketches a plan before changing code")
    if approval_l in {"readonly", "read-only"}:
        out.append("sometimes explores read-only before editing")
    if write_edits >= 4:
        out.append("iterates with several edits in one sitting")
    elif write_edits >= 1 and tool_calls <= 3:
        out.append("prefers focused edits over long tool chains")
    if bash_calls >= 3 and bash_calls > write_edits:
        out.append("comfortable driving work through the shell")
    if compaction_count > 0:
        out.append("works on longer threads that need compaction")
    if subagent_runs >= 2:
        out.append("delegates parallel subtasks when useful")
    if interrupted or exit_status == "Interrupted":
        out.append("steers or stops mid-run to correct course")
    return out


def record_style_observations(
    store: MemoryStore,
    signals: list[str],
    *,
    session_id: str = "",
) -> int:
    """Persist soft style signals to episodic log and WORKING.md."""
    added = 0
    for raw in signals:
        text = _normalize_signal(raw)
        if not text:
            continue
        store.record_episode(
            kind="style",
            summary=text,
            session_id=session_id,
            payload={"observed_at": time.time()},
            scope="user",
        )
        try:
            append_signal(text)
        except ValueError:
            continue
        added += 1
    return added


def observe_session_turn(
    store: MemoryStore,
    *,
    session_id: str = "",
    mode: str = "",
    approval: str = "",
    extra: dict[str, Any] | None = None,
    interrupted: bool = False,
) -> int:
    """After a REPL turn, capture fluid working-style hints (never blocking)."""
    payload = extra or {}
    stats = payload.get("model_stats") if isinstance(payload.get("model_stats"), dict) else {}
    exit_status = str(payload.get("exit_status") or "")
    signals = infer_style_signals(
        mode=mode,
        approval=approval,
        tool_calls=int(stats.get("api_calls") or payload.get("api_calls") or 0),
        write_edits=int(stats.get("write_edits") or 0),
        bash_calls=int(stats.get("bash_calls") or 0),
        compaction_count=int(stats.get("compaction_count") or 0),
        subagent_runs=int(stats.get("subagent_runs") or 0),
        interrupted=interrupted,
        exit_status=exit_status,
    )
    if not signals:
        return 0
    return record_style_observations(store, signals, session_id=session_id)


def _recent_style_episodes(store: MemoryStore, *, limit: int = _MAX_EPISODE_SIGNALS) -> list[str]:
    rows = store.episodes(limit=24, scope="user")
    seen: set[str] = set()
    out: list[str] = []
    for ep in rows:
        if ep.kind != "style":
            continue
        key = _signal_key(ep.summary)
        if key in seen:
            continue
        seen.add(key)
        out.append(ep.summary.strip())
        if len(out) >= limit:
            break
    return out


def format_working_section(body: str) -> str:
    from kite.memory.secure_io import wrap_untrusted_user_content

    text = (body or "").strip()
    if not text:
        return ""
    wrapped = wrap_untrusted_user_content(
        text,
        source="WORKING.md",
    )
    return f"# Working rhythm\n{wrapped}"


def render_working_context(store: MemoryStore, *, max_chars: int = 900) -> str:
    """Build the fluid working-style block for the system prompt."""
    parts: list[str] = []
    narrative = read_narrative()
    if narrative and narrative != _DEFAULT_PIN.strip():
        parts.append(narrative)

    signals = read_signals()
    recent = _recent_style_episodes(store)
    merged: list[str] = []
    seen: set[str] = set()
    for item in signals + recent:
        key = _signal_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    if merged:
        lines = ["### Signals"] + [f"- {s}" for s in merged[:_MAX_SIGNALS]]
        parts.append("\n".join(lines))

    if not parts:
        return ""
    body = "\n\n".join(parts)
    if len(body) > max_chars:
        body = body[: max_chars - 24] + "\n\n...[truncated]..."
    return format_working_section(body)
