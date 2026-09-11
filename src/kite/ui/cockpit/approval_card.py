"""Foreground approval cards — what / why / risk / scope."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from kite.ui.cockpit.view_model import ApprovalState
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def render_approval_card(state: ApprovalState, *, width: int = 72) -> Panel:
    body = Text()
    body.append(f"{GUTTER}{glyph('warn')} ", style="kite.pending")
    body.append("Approval required\n", style="kite.pending bold")
    if state.tool:
        body.append(f"{GUTTER}{state.tool}\n", style="kite.tool bold")
    if state.summary:
        body.append(f"{GUTTER}{state.summary}\n", style="")
    if state.scope:
        body.append(f"{GUTTER}scope: {state.scope}\n", style="kite.muted")
    if state.risk:
        body.append(f"{GUTTER}risk: {state.risk}\n", style="kite.error" if state.mandatory else "kite.pending")
    body.append(f"{GUTTER}\n", style="")
    body.append(f"{GUTTER}[a] allow once  [s] session  ", style="kite.muted")
    if not state.mandatory:
        body.append("[p] always  ", style="kite.muted")
    body.append("[n] deny  [q] stop\n", style="kite.muted")
    return Panel(body, title="Approval", border_style="yellow", width=min(width, 88), padding=(0, 1))
