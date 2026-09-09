"""Numbered left-bar pickers — shared by CLI and REPL."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

_PICK_SHOW = 40
REFRESH_PICK = "__refresh__"


def can_prompt() -> bool:
    """True when we can ask a question (stdin TTY; we print prompts on stderr)."""
    from kite.util.tty import is_interactive_tty

    if not is_interactive_tty(require_stdout=False):
        return False
    return sys.stderr.isatty()


def numbered_pick(
    console: Console,
    items: list[tuple[str, str]],
    *,
    current: str | None = None,
    title: str,
    noun: str,
    show: int = _PICK_SHOW,
    refreshable: bool = False,
) -> str | None:
    """Print a numbered list and return the chosen id, or None if cancelled.

    When refreshable=True, typing ``r`` / ``refresh`` returns REFRESH_PICK so the
    caller can re-fetch from the API and redraw.
    """
    from kite.ui.credentials import render_pick_list

    if not items:
        return None
    shown = list(items[:show])
    if current and not any(item_id == current for item_id, _ in shown):
        for pair in items:
            if pair[0] == current:
                shown = [pair, *shown][:show]
                break

    extra = max(0, len(items) - len(shown))
    console.print(
        render_pick_list(
            shown,
            title=title,
            current=current,
            extra=extra,
            noun=noun,
            refreshable=refreshable,
        )
    )

    prompt = f"Pick {noun}"
    if refreshable:
        prompt += " (r = refresh)"
    prompt += ": "
    try:
        raw = console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[kite.pending]Cancelled[/]")
        return None

    if not raw or raw.lower() in {"q", "quit"}:
        console.print("[kite.pending]Cancelled[/]")
        return None

    if refreshable and raw.lower() in {"r", "refresh"}:
        return REFRESH_PICK

    ids = {item_id: item_id for item_id, _ in items}
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(shown):
            return shown[idx - 1][0]
        console.print("[kite.pending]Number out of range[/]")
        return None
    if raw in ids:
        return raw
    hits = [
        item_id
        for item_id, label in items
        if raw.lower() in item_id.lower() or raw.lower() in label.lower()
    ]
    hits = list(dict.fromkeys(hits))
    if len(hits) == 1:
        return hits[0]
    console.print(f"[kite.pending]No matching {noun}[/]")
    return None


def confirm(console: Console, question: str, *, default: bool = True) -> bool:
    """Y/n prompt. Empty uses default. Cancel / EOF → False."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        raw = console.input(f"{question}{suffix}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[kite.pending]Cancelled[/]")
        return False
    if not raw:
        return default
    if raw in {"y", "yes"}:
        return True
    if raw in {"n", "no", "q", "quit"}:
        return False
    return default
