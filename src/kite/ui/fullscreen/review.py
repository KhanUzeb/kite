"""Changes and verification panels for fullscreen layout."""

from __future__ import annotations

from rich.text import Text

from kite.ui.diff import render_diff_stat
from kite.ui.fullscreen.model import ReviewState, VerificationCheck
from kite.ui.style import GUTTER
from kite.ui.theme import glyph


def _status_mark(status: str) -> tuple[str, str]:
    if status in {"pass", "ok", "verified"}:
        return glyph("ok"), "kite.success"
    if status in {"fail", "failed"}:
        return glyph("fail"), "kite.error"
    if status in {"pending", "running"}:
        return glyph("spin"), "kite.pending"
    return glyph("todo"), "kite.muted"


def render_changes_panel(review: ReviewState, *, max_files: int = 8) -> Text:
    block = Text()
    count = len(review.files)
    block.append(f"{GUTTER}Changes", style="kite.highlight bold")
    if count:
        block.append(f"  {count} files  ", style="kite.muted")
        block.append_text(render_diff_stat(review.total_added, review.total_deleted, bar=False))
    else:
        block.append("  none yet", style="kite.muted")
    block.append("\n")
    block.append(f"{GUTTER}{'─' * 28}\n", style="kite.muted")
    for item in review.files[:max_files]:
        block.append(f"{GUTTER}", style="kite.muted")
        block.append(item.path[-40:], style="kite.tool")
        block.append("  ", style="")
        block.append_text(render_diff_stat(item.added, item.deleted, bar=False))
        block.append("\n")
    if count > max_files:
        block.append(f"{GUTTER}… +{count - max_files} more\n", style="kite.muted")
    return block


def render_verification_panel(
    checks: list[VerificationCheck],
    review: ReviewState,
    *,
    max_checks: int = 6,
) -> Text:
    block = Text()
    block.append(f"{GUTTER}VERIFICATION\n", style="kite.highlight bold")
    if not checks and not review.verified:
        label = review.verification_label or "unverified"
        mark, style = _status_mark("pending" if label == "unverified" else label)
        block.append(f"{GUTTER}{mark} ", style=style)
        block.append(label, style=style)
        block.append("\n")
        return block
    for check in checks[:max_checks]:
        mark, style = _status_mark(check.status)
        block.append(f"{GUTTER}{mark} ", style=style)
        block.append(f"{check.name:<14}", style="")
        summary = check.summary or check.status
        block.append(summary[:32], style="kite.muted")
        block.append("\n")
    if review.verified:
        block.append(f"{GUTTER}{glyph('ok')} verified\n", style="kite.success")
    elif review.verification_label:
        block.append(f"{GUTTER}{glyph('warn')} {review.verification_label}\n", style="kite.pending")
    return block
