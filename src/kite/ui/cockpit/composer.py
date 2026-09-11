"""Unified composer pills — mode, model, attachments."""

from __future__ import annotations

from rich.text import Text

from kite.ui.cockpit.view_model import ComposerState
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def render_composer_pills(state: ComposerState, *, placeholder: str = "Ask KITE…") -> Text:
    line = Text()
    pills: list[tuple[str, str]] = []
    for att in state.attachments[:4]:
        label = att if len(att) <= 24 else "…" + att[-22:]
        pills.append((f"@{label}", "kite.highlight"))
    if state.mode:
        pills.append((state.mode, "kite.brand"))
    if state.provider or state.model:
        model = state.model.split("/")[-1] if state.model else ""
        prov = state.provider or ""
        label = model or prov
        if prov and model and not state.model.startswith(prov):
            label = f"{prov}/{model}"
        pills.append((label[:28], "kite.muted"))
    if state.approval:
        pills.append((state.approval, "kite.pending"))
    if state.queued:
        pills.append((f"queue {state.queued}", "kite.muted"))

    line.append(f"{GUTTER}{glyph('prompt')} ", style="kite.brand")
    line.append(placeholder, style="kite.muted")
    if pills:
        line.append("  ", style="")
        for i, (text, style) in enumerate(pills):
            if i:
                line.append(" ", style="")
            line.append("[", style="kite.muted")
            line.append(text, style=style)
            line.append("]", style="kite.muted")
    line.append("\n")
    return line


def render_composer_actions(*, plan: bool = False, build: bool = True) -> Text:
    line = Text()
    line.append(f"{GUTTER}", style="kite.muted")
    if plan:
        line.append("[Plan]", style="kite.muted")
        line.append("  ", style="")
    if build:
        line.append("[Build]", style="kite.brand")
    line.append("\n")
    return line
