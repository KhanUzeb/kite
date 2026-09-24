"""Turn routing (§6, propose-only): cheap model for simple turns, upgrade on signal.

Status: proposal + behind-flag helper. Not wired into the loop until §8
validation shows cost per completed task drops with no success regression.

Heuristic mirrors the guide's router: short casual Q&A and read-only lookups
stay on the cheap tier; anything mutating, multi-step, or ambiguous upgrades.
Planner choice changes worker spend, so the whole tree is measured (§6).
"""

from __future__ import annotations


def route_turn(
    task: str,
    *,
    enabled: bool = False,
    has_edits: bool = False,
) -> str:
    """Return 'cheap' or 'frontier'. Disabled by default (flag)."""
    if not enabled:
        return "frontier"
    text = (task or "").strip()
    if has_edits:
        return "frontier"
    if len(text) < 80 and (text.endswith("?") or text.lower() in {"hi", "thanks", "ok"}):
        return "cheap"
    mutating = ("fix", "implement", "add", "create", "refactor", "debug", "build", "write", "update")
    if any(w in text.lower() for w in mutating):
        return "frontier"
    return "cheap"
