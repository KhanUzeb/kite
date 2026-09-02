"""Session clock — injected into the system prompt so the model knows "now"."""

from __future__ import annotations

from datetime import datetime, timezone


def session_time_section() -> str:
    """Compact UTC + local timestamp block (recomputed each run)."""
    utc = datetime.now(timezone.utc)
    local = datetime.now().astimezone()
    return (
        "## Session time\n"
        f"- UTC: {utc.strftime('%Y-%m-%d %H:%M')} ({utc.tzname() or 'UTC'})\n"
        f"- Local: {local.strftime('%Y-%m-%d %H:%M %Z')}"
    )
