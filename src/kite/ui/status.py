"""Shared status-line formatting for Rich footer and prompt_toolkit toolbar."""

from __future__ import annotations

import shutil

from rich.text import Text

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name
from kite.models.reasoning import reasoning_badge
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_SEP
from kite.ui.theme import glyph

_CONTEXT_BAR_WIDTH = 8


def _terminal_compact() -> bool:
    try:
        width = shutil.get_terminal_size(fallback=(120, 24)).columns
    except OSError:
        width = 120
    return width < 100


def cache_meter(ratio: float | None, *, width: int = _CONTEXT_BAR_WIDTH) -> str:
    if ratio is None or ratio <= 0:
        return ""
    clamped = max(0.0, min(1.0, ratio))
    filled = int(round(clamped * width))
    bar = glyph("bar_fill") * filled + glyph("bar_empty") * (width - filled)
    return f"cache {bar} {clamped:.0%}"


def format_session_row(meta, *, current: str | None = None) -> str:
    """One-line session picker label (date, title, model, id)."""
    from kite.memory.session_format import format_session_picker_label

    return format_session_picker_label(meta, current=current)


def active_task_count(state: SessionUiState) -> int:
    return (1 if state.busy else 0) + max(0, state.queued)


def format_running_status(state: SessionUiState) -> str:
    if state.retry_until is not None:
        import time

        left = state.retry_until - time.monotonic()
        if left > 0:
            secs = max(1, int(left + 0.999))
            label = state.retry_label or "provider retry"
            return f"retrying in {secs}s  {label}"
    if state.compacting and not state.running_label:
        import time

        from kite.ui.animations import loader_glyph

        tick = int(time.monotonic() * 10)
        spin = loader_glyph("spin", tick)
        return f"{spin} compacting context"
    if not state.busy or not state.running_label:
        return ""
    import time

    from kite.ui.animations import loader_glyph

    ts = state.running_since or "—"
    label = state.running_label
    if len(label) > 72:
        label = label[:69] + "…"
    tick = int(time.monotonic() * 10)
    spin = loader_glyph("spin", tick)
    line = f"{spin} [{ts}] {label}  running"
    preview = sanitize_status_text(state.activity_preview)
    if preview:
        if len(preview) > 60:
            preview = preview[:57] + "…"
        line += f"  › {preview}"
    return line


def sanitize_status_text(text: str) -> str:
    return " ".join((text or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").split())


def format_metrics_tail(state: SessionUiState) -> str:
    parts: list[str] = []
    if state.busy and state.ttft_ms is not None and state.stream_chars < 400:
        parts.append(f"ttft {state.ttft_ms}ms")
    if state.busy or state.tps > 0:
        parts.append(f"{state.tps:.0f} tok/s" if state.tps > 0 else "— tok/s")
    if state.cache_hit_tokens > 0 or state.cache_hit_ratio > 0:
        meter = cache_meter(state.cache_hit_ratio)
        parts.append(meter or f"cache {state.cache_hit_ratio:.0%}")
    elif state.busy and state.window:
        parts.append("cache —")
    meter = context_meter(state.context_pct)
    if meter:
        parts.append(meter)
    elif state.tokens and state.window:
        parts.append(f"ctx {state.tokens}/{state.window}")
    parts.append(f"${state.cost:.3f}")
    return " · ".join(parts)


def context_meter(pct: float | None, *, width: int = _CONTEXT_BAR_WIDTH) -> str:
    if pct is None:
        return ""
    clamped = max(0.0, min(1.0, pct))
    filled = int(round(clamped * width))
    bar = glyph("bar_fill") * filled + glyph("bar_empty") * (width - filled)
    return f"ctx {bar} {clamped:.0%}"


def format_model_label(state: SessionUiState) -> str:
    if state.provider:
        return f"{state.provider}/{state.model}"
    return state.model or "—"


_VERIFY_LABELS = {
    "changed_unverified": "unverified edits",
    "failed": "verify failed",
    "partial": "partial verify",
    "unverified": "unverified",
    "blocked": "submit blocked",
}


def _verification_badge(status: str) -> str | None:
    key = (status or "").strip().lower()
    if not key or key in {"idle", "verified"}:
        return None
    return _VERIFY_LABELS.get(key, f"verify {key.replace('_', ' ')}")


def status_context_parts(state: SessionUiState) -> list[str]:
    parts: list[str] = [format_model_label(state)]
    if state.reasoning and state.reasoning != "auto":
        parts.append(reasoning_badge(state.reasoning) or state.reasoning)
    if state.pending_attach:
        parts.append(f"+{state.pending_attach}")
    if state.active_jobs:
        parts.append(f"jobs {state.active_jobs}")
    elif state.active_subagents:
        parts.append(f"agents {state.active_subagents}")
    if state.git_branch:
        parts.append(state.git_branch)
    badge = _verification_badge(state.verification_status)
    if badge:
        parts.append(badge)
    if state.awaiting_approval:
        parts.insert(0, f"approve {state.awaiting_approval}")
    if state.busy:
        parts.append("working")
        tasks = active_task_count(state)
        if tasks:
            parts.append(f"{tasks} task{'s' if tasks != 1 else ''}")
    elif state.queued:
        parts.append(f"queued {state.queued}")
    if state.interrupted:
        parts.append("interrupted")
    return parts


def _segment_style(text: str) -> str:
    if text.startswith("approve "):
        return "kite.pending"
    if text == "working":
        return "kite.highlight"
    if text.startswith("verify ") or text in _VERIFY_LABELS.values():
        return "kite.pending"
    return "kite.muted"


def status_segments(state: SessionUiState) -> list[tuple[str, str]]:
    """Ordered (text, rich_style) segments shown after the kite brand."""
    if state.awaiting_approval:
        label = state.awaiting_approval or "tool"
        return [("approval", "kite.pending"), (label, "kite.pending")]

    mode_label = "plan" if state.mode is AgentMode.PLAN else state.mode.value
    model = format_model_label(state)
    cost = f"${state.cost:.3f}"

    if state.busy:
        action = state.running_label or "working"
        if len(action) > 48:
            action = action[:45] + "…"
        return [
            (mode_label, mode_style(state)),
            (action, "kite.highlight"),
            (cost, "kite.muted"),
        ]

    return [
        (mode_label, mode_style(state)),
        (model, "kite.muted"),
        (cost, "kite.muted"),
    ]


def status_detail_lines(state: SessionUiState) -> list[str]:
    """Extended status for /status — shortcuts, paths, and subsystem detail."""
    lines = [
        f"{state.mode.value} · {approval_display_name(state.approval)} · "
        f"sandbox {'restricted' if state.sandbox_restricted else 'host'} · "
        f"{format_model_label(state)} · effort {state.reasoning}",
    ]
    metrics = format_metrics_tail(state)
    if metrics:
        lines.append(metrics)
    for bit in status_context_parts(state):
        if bit not in {state.git_branch, format_model_label(state)}:
            lines.append(bit)
    return lines


def format_status_tail(state: SessionUiState) -> str:
    parts = [text for text, _ in status_segments(state)]
    return f" {SYMBOL_SEP} ".join(parts)


def render_status(state: SessionUiState) -> Text:
    """Rich status line — matches toolbar fields with semantic colors."""
    line = Text()
    line.append("kite", style="kite.brand")
    for text, style in status_segments(state):
        line.append(f" {SYMBOL_SEP} ", style="kite.muted")
        line.append(text, style=style)
    return line


def approval_style(state: SessionUiState) -> str:
    if state.approval in {ApprovalMode.APPROVE, ApprovalMode.YOLO}:
        return "kite.pending" if state.approval is ApprovalMode.APPROVE else "kite.build"
    if state.approval is ApprovalMode.READONLY:
        return "kite.muted"
    return "kite.muted"


def mode_style(state: SessionUiState) -> str:
    return "kite.plan" if state.mode is AgentMode.PLAN else "kite.build"
