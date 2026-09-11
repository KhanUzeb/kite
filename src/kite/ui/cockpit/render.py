"""Full-screen cockpit layout — projection of ``RunViewModel``."""

from __future__ import annotations

from rich.console import Console, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from kite.ui.cockpit.approval_card import render_approval_card
from kite.ui.cockpit.composer import render_composer_actions, render_composer_pills
from kite.ui.cockpit.mode import cockpit_layout_tier
from kite.ui.cockpit.review import render_changes_panel, render_verification_panel
from kite.ui.cockpit.view_model import RunViewModel, TimelineEntry
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def _status_line(model: RunViewModel) -> Text:
    line = Text()
    parts = [
        ("KITE", "kite.brand bold"),
        (model.repo or "repo", "kite.muted"),
        (model.branch or "branch", "kite.muted"),
        (model.mode, "kite.highlight"),
        (model.model.split("/")[-1] if model.model else "model", "kite.muted"),
    ]
    if model.context.pct:
        parts.append((f"context {model.context.pct:.0f}%", "kite.muted"))
    for i, (text, style) in enumerate(parts):
        if i:
            line.append(f" {glyph('sep')} ", style="kite.muted")
        line.append(text, style=style)
    line.append("\n")
    return line


def _timeline_mark(entry: TimelineEntry) -> tuple[str, str]:
    if entry.status == "running":
        return glyph("spin"), "kite.pending"
    if entry.status == "ok":
        return glyph("ok"), "kite.success"
    if entry.status in {"failed", "blocked"}:
        return glyph("fail"), "kite.error"
    return glyph("todo"), "kite.muted"


def render_timeline(model: RunViewModel, *, max_items: int = 12) -> Text:
    block = Text()
    if model.goal:
        block.append(f"{GUTTER}Goal\n", style="kite.highlight bold")
        block.append(f"{GUTTER}{model.goal[:80]}\n", style="")
        block.append(f"{GUTTER}{'─' * 32}\n", style="kite.muted")
    if model.plan_total:
        block.append(f"{GUTTER}Plan  ", style="kite.muted")
        block.append(f"{glyph('ok')} {model.plan_done}/{model.plan_total}\n", style="kite.task")
    block.append(f"{GUTTER}Timeline\n", style="kite.muted bold")
    items = model.timeline[-max_items:]
    for entry in items:
        mark, style = _timeline_mark(entry)
        block.append(f"{GUTTER}{mark} ", style=style)
        block.append(f"{entry.kind:<12}", style="kite.muted")
        block.append(entry.title[:48], style="")
        if entry.duration_ms is not None:
            block.append(f"  {entry.duration_ms / 1000:.1f}s", style="kite.muted")
        block.append("\n")
    if not items and not model.goal:
        block.append(f"{GUTTER}(waiting for events)\n", style="kite.muted")
    return block


def render_work_panel(model: RunViewModel) -> Text:
    block = Text()
    block.append(f"{GUTTER}WORK\n", style="kite.highlight bold")
    status = model.status
    mark = glyph("spin") if status == "running" else glyph("ok") if status in {"submitted", "done"} else glyph("todo")
    block.append(f"{GUTTER}{mark} Active  {status}\n", style="kite.muted")
    if model.composer.queued:
        block.append(f"{GUTTER}Queued  {model.composer.queued}\n", style="kite.muted")
    block.append(f"{GUTTER}Turn {model.turn}  cost ${model.cost:.4f}\n", style="kite.muted")
    if model.agents.workers:
        block.append(f"{GUTTER}\nCREW\n", style="kite.highlight")
        for worker in model.agents.workers[-6:]:
            wmark = glyph("spin") if worker.status == "running" else glyph("ok") if worker.status == "completed" else glyph("todo")
            block.append(f"{GUTTER}{wmark} {worker.name:<12} {worker.status}\n", style="kite.muted")
    return block


def render_inspect_panel(model: RunViewModel) -> Text:
    block = Text()
    block.append(f"{GUTTER}Status\n", style="kite.highlight bold")
    mark = glyph("spin") if model.status == "running" else glyph("warn") if model.approval.active else glyph("ok")
    block.append(f"{GUTTER}{mark} {model.status}\n", style="")
    if model.active_tool:
        block.append(f"{GUTTER}tool: {model.active_tool}\n", style="kite.tool")
    block.append("\n")
    block.append_text(render_verification_panel(model.verification_checks, model.review))
    block.append("\n")
    block.append_text(render_changes_panel(model.review))
    if model.errors:
        block.append(f"{GUTTER}\nNext\n", style="kite.highlight")
        block.append(f"{GUTTER}{model.errors[-1][:64]}\n", style="kite.error")
    return block


def render_cockpit_text(model: RunViewModel, *, cols: int = 120, rows: int = 40) -> Text:
    """Single-column fallback when layout tier is reduced."""
    tier = cockpit_layout_tier(cols, rows)
    block = Text()
    block.append_text(_status_line(model))
    block.append(f"{GUTTER}{'═' * min(cols - 2, 78)}\n", style="kite.muted")
    if tier == "none":
        block.append(f"{GUTTER}Terminal too small for cockpit — use compact mode.\n", style="kite.pending")
        return block
    block.append_text(render_work_panel(model))
    block.append("\n")
    block.append_text(render_timeline(model, max_items=10 if tier == "reduced" else 14))
    block.append("\n")
    block.append_text(render_inspect_panel(model))
    block.append("\n")
    block.append_text(render_composer_pills(model.composer))
    block.append_text(render_composer_actions(plan=True, build=True))
    return block


def build_cockpit_layout(model: RunViewModel, *, cols: int = 120, rows: int = 40) -> Layout | Text:
    tier = cockpit_layout_tier(cols, rows)
    if tier == "none":
        return render_cockpit_text(model, cols=cols, rows=rows)

    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="work", ratio=2),
        Layout(name="run", ratio=5),
        Layout(name="inspect", ratio=3),
    )
    layout["header"].update(Panel(_status_line(model), border_style="dim", padding=(0, 1)))
    layout["work"].update(Panel(render_work_panel(model), title="Work", border_style="dim"))
    run_body = render_timeline(model, max_items=14 if tier == "full" else 10)
    layout["run"].update(Panel(run_body, title="Run", border_style="cyan"))
    layout["inspect"].update(Panel(render_inspect_panel(model), title="Inspect", border_style="dim"))
    footer = Text()
    footer.append_text(render_composer_pills(model.composer))
    footer.append_text(render_composer_actions(plan=True, build=True))
    layout["footer"].update(Panel(footer, border_style="dim", padding=(0, 1)))
    return layout


def render_cockpit(
    console: Console,
    model: RunViewModel,
    *,
    cols: int | None = None,
    rows: int | None = None,
) -> None:
    cols = cols or console.width or 120
    rows = rows or console.height or 40
    if model.approval.active:
        console.print(render_approval_card(model.approval, width=cols - 4))
    body: RenderableType = build_cockpit_layout(model, cols=cols, rows=rows)
    console.print(body)
