"""Shared status-line formatting for Rich footer and prompt_toolkit toolbar."""

from __future__ import annotations

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name
from kite.models.reasoning import reasoning_badge
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_SEP
from kite.ui.theme import glyph

_CONTEXT_BAR_WIDTH = 8


def format_token_count(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M tok"
    if tokens >= 10_000:
        return f"{tokens / 1_000:.1f}k tok"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.2f}k tok"
    return f"{tokens} tok"


def cache_meter(ratio: float | None, *, width: int = _CONTEXT_BAR_WIDTH) -> str:
    """Mini bar: cache ████░░░░ 25%"""
    if ratio is None or ratio <= 0:
        return ""
    clamped = max(0.0, min(1.0, ratio))
    filled = int(round(clamped * width))
    bar = glyph("bar_fill") * filled + glyph("bar_empty") * (width - filled)
    return f"cache {bar} {clamped:.0%}"


def format_session_row(meta, *, current: str | None = None) -> str:
    """One-line session picker label with token/cache/cost when available."""
    from kite.memory.session_analytics import load_session_stats

    label = (meta.label or meta.task or "").strip()[:36]
    row = f"{meta.id}  {meta.provider}/{meta.model}"
    if label:
        row += f"  {label}"
    if current and meta.id == current:
        row += "  *"
    stats = load_session_stats(meta.id)
    if stats is None:
        return row
    bits: list[str] = []
    if stats.estimated_tokens:
        bits.append(format_token_count(stats.estimated_tokens))
    if stats.cost > 0:
        bits.append(f"${stats.cost:.3f}")
    if stats.cache_hit_tokens:
        denom = max(stats.estimated_tokens, stats.cache_hit_tokens, 1)
        bits.append(cache_meter(stats.cache_hit_tokens / denom) or f"cache {stats.cache_hit_tokens}")
    if stats.api_calls:
        bits.append(f"{stats.api_calls} calls")
    if bits:
        row += "  · " + " · ".join(bits)
    return row


def active_task_count(state: SessionUiState) -> int:
    """Current turn plus queued follow-ups."""
    return (1 if state.busy else 0) + max(0, state.queued)


def format_running_status(state: SessionUiState) -> str:
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
    preview = (state.activity_preview or "").strip()
    if preview:
        if len(preview) > 56:
            preview = preview[:53] + "…"
        line += f"  › {preview}"
    return line


def format_metrics_tail(state: SessionUiState) -> str:
    """Throughput, cache, context, and cost — always-on footer metrics."""
    parts: list[str] = []
    if state.tokens:
        parts.append(format_token_count(state.tokens))
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
    if state.busy and state.n_calls:
        parts.append(f"{state.n_calls} calls")
    parts.append(f"${state.cost:.3f}")
    return " · ".join(parts)


def context_meter(pct: float | None, *, width: int = _CONTEXT_BAR_WIDTH) -> str:
    """Mini bar: ctx ████░░░░ 45%"""
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
    """Model, context, cost — everything after mode and approval."""
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


def format_status_tail(state: SessionUiState) -> str:
    """Everything after the kite brand — shared by render + composer toolbar."""
    import shutil

    try:
        width = shutil.get_terminal_size(fallback=(120, 24)).columns
    except OSError:
        width = 120
    compact = width < 100
    mode_label = "plan" if state.mode is AgentMode.PLAN else state.mode.value
    mode_bits = [mode_label, approval_display_name(state.approval)]
    if not compact and state.mode is AgentMode.PLAN and state.todos:
        done = sum(1 for t in state.todos if t.status == "completed")
        mode_bits.append(f"list {done}/{len(state.todos)}")
    if state.sandbox_restricted:
        mode_bits.append("restricted")
    parts = [*mode_bits]
    ctx = status_context_parts(state)
    if compact:
        for bit in ctx:
            if bit.startswith("approve "):
                parts.insert(0, bit)
                break
        if state.busy:
            parts.append("working")
        elif state.queued:
            parts.append(f"q{state.queued}")
    else:
        parts.extend(ctx)
    return f" {SYMBOL_SEP} ".join(parts)


def approval_style(state: SessionUiState) -> str:
    if state.approval in {ApprovalMode.APPROVE, ApprovalMode.YOLO}:
        return "kite.pending" if state.approval is ApprovalMode.APPROVE else "kite.build"
    if state.approval is ApprovalMode.READONLY:
        return "kite.muted"
    return "kite.muted"


def mode_style(state: SessionUiState) -> str:
    return "kite.plan" if state.mode is AgentMode.PLAN else "kite.build"
