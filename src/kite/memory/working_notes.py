"""Agent-maintained working notes — one small file with a line budget.

Repeated work in one environment gets shorter when the agent keeps its own
notes (what was tried, what worked, environment quirks) instead of
rediscovering them every run. Rules, from the token-efficiency guide:

- Rewrite the file instead of appending — appending grows without bound.
- Line budget (default 40): durable intent first, details after.
- Loaded at start only when the file exists, so absent notes cost zero tokens.
"""

from __future__ import annotations

from pathlib import Path

NOTES_FILENAME = "NOTES.md"
MAX_LINES = 40
MAX_CHARS = 2_000


def notes_path(cwd: str | Path) -> Path:
    return Path(cwd).expanduser().resolve() / ".kite" / NOTES_FILENAME


def load_notes(cwd: str | Path | None, *, max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> str:
    """Read working notes capped to budget; "" when absent (zero tokens)."""
    if cwd is None:
        return ""
    try:
        text = notes_path(cwd).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text:
        return ""
    lines = text.splitlines()[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[: max_chars - 20] + "\n...[truncated]..."
    return out


def save_notes(cwd: str | Path, text: str) -> Path:
    """Rewrite the whole file (never append), enforcing the line budget."""
    path = notes_path(cwd)
    lines = text.strip().splitlines()[:MAX_LINES]
    out = "\n".join(lines)
    if len(out) > MAX_CHARS:
        out = out[: MAX_CHARS - 20] + "\n...[truncated]..."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out + "\n", encoding="utf-8")
    return path


def notes_block(cwd: str | Path | None) -> str:
    """Setup-message block, or "" when no notes exist."""
    body = load_notes(cwd)
    if not body:
        return ""
    return f"## Working notes (agent-maintained, rewrite — don't append)\n{body}"
