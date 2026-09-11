"""Full-screen layout — fluid stream center, inspect side panels."""

from __future__ import annotations

from rich.console import Console, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from kite.ui.fullscreen.approval_card import render_approval_card
from kite.ui.fullscreen.mode import fullscreen_layout_tier
from kite.ui.fullscreen.model import FullscreenModel, StreamLine
from kite.ui.fullscreen.review import render_changes_panel, render_verification_panel
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def _status_line(model: FullscreenModel) -> Text:
    line = Text()
    parts = [
        ("kite", "kite.brand bold"),
        (model.repo or "repo", "kite.muted"),
        (model.branch or "branch", "kite.muted"),
        (model.mode, "kite.highlight"),
        (model.model.split("/")[-1] if model.model else "model", "kite.muted"),
    ]
    if model.context_pct:
        parts.append((f"ctx {model.context_pct:.0f}%", "kite.muted"))
    for i, (text, style) in enumerate(parts):
        if i:
            line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append(text, style=style)
    line.append("\n")
    return line


def _stream_style(line: StreamLine) -> str:
    if line.status == "running":
        return "kite.highlight"
    if line.status == "failed":
        return "kite.error"
    return ""


def render_stream(model: FullscreenModel, *, max_items: int = 16) -> Text:
    block = Text()
    block.append(f"{GUTTER}Stream\n", style="kite.muted bold")
    items = model.stream[-max_items:]
    for entry in items:
        block.append(f"{GUTTER}{entry.mark} ", style=_stream_style(entry) or "kite.muted")
        block.append(f"{entry.label:<10}", style="kite.tool" if entry.label != "assistant" else "kite.answer")
        detail = entry.detail[:56]
        if detail:
            block.append(detail, style="kite.muted" if entry.label != "assistant" else "")
        block.append("\n")
    if not items:
        block.append(f"{GUTTER}(waiting for events)\n", style="kite.muted")
    return block


def render_work_panel(model: FullscreenModel) -> Text:
    block = Text()
    block.append(f"{GUTTER}WORK\n", style="kite.highlight bold")
    mark = glyph("spin") if model.status == "running" else glyph("ok") if model.status in {"submitted", "done"} else glyph("todo")
    block.append(f"{GUTTER}{mark} {model.status}\n", style="kite.muted")
    if model.plan_total:
        block.append(f"{GUTTER}checklist  {model.plan_done}/{model.plan_total}\n", style="kite.task")
    if model.composer.queued:
        block.append(f"{GUTTER}queued  {model.composer.queued}\n", style="kite.muted")
    block.append(f"{GUTTER}turn {model.turn}  ${model.cost:.4f}\n", style="kite.muted")
    if model.active_tool:
        block.append(f"{GUTTER}tool  {model.active_tool}\n", style="kite.tool")
    if model.agents:
        block.append(f"{GUTTER}\nCREW\n", style="kite.highlight")
        for worker in model.agents[-6:]:
            wmark = glyph("spin") if worker.status == "running" else glyph("ok")
            block.append(f"{GUTTER}{wmark} {worker.name:<12} {worker.status}\n", style="kite.muted")
    return block


def render_inspect_panel(model: FullscreenModel) -> Text:
    block = Text()
    block.append_text(render_verification_panel(model.verification_checks, model.review))
    block.append("\n")
    block.append_text(render_changes_panel(model.review))
    if model.errors:
        block.append(f"{GUTTER}\nNext\n", style="kite.highlight")
        block.append(f"{GUTTER}{model.errors[-1][:64]}\n", style="kite.error")
    return block


def render_footer(model: FullscreenModel) -> Text:
    line = Text()
    line.append(f"{GUTTER}{glyph('prompt')} ", style="kite.brand")
    line.append("composer below", style="kite.muted")
    pills: list[tuple[str, str]] = []
    if model.composer.mode:
        pills.append((model.composer.mode, "kite.brand"))
    if model.model:
        pills.append((model.model.split("/")[-1][:20], "kite.muted"))
    if model.composer.approval:
        pills.append((model.composer.approval, "kite.pending"))
    for i, (text, style) in enumerate(pills):
        line.append("  ", style="")
        line.append("[", style="kite.muted")
        line.append(text, style=style)
        line.append("]", style="kite.muted")
    line.append("  ", style="")
    line.append("Ctrl+Space · /fullscreen off", style="kite.muted")
    line.append("\n")
    return line


def build_fullscreen_layout(model: FullscreenModel, *, cols: int = 120, rows: int = 40) -> Layout | Text:
    tier = fullscreen_layout_tier(cols, rows)
    if tier == "none":
        block = Text()
        block.append_text(_status_line(model))
        block.append(f"{GUTTER}Terminal too small for fullscreen (need ≥100×30).\n", style="kite.pending")
        return block

    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="work", ratio=2),
        Layout(name="stream", ratio=5),
        Layout(name="inspect", ratio=3),
    )
    layout["header"].update(Panel(_status_line(model), border_style="dim", padding=(0, 1)))
    layout["work"].update(Panel(render_work_panel(model), title="Work", border_style="dim"))
    max_stream = 14 if tier == "full" else 10
    layout["stream"].update(Panel(render_stream(model, max_items=max_stream), title="Stream", border_style="cyan"))
    layout["inspect"].update(Panel(render_inspect_panel(model), title="Inspect", border_style="dim"))
    layout["footer"].update(Panel(render_footer(model), border_style="dim", padding=(0, 1)))
    return layout


def render_fullscreen(
    console: Console,
    model: FullscreenModel,
    *,
    cols: int | None = None,
    rows: int | None = None,
) -> RenderableType:
    cols = cols or console.width or 120
    rows = rows or console.height or 40
    if model.approval.active:
        return render_approval_card(model.approval, width=cols - 4)
    return build_fullscreen_layout(model, cols=cols, rows=rows)
