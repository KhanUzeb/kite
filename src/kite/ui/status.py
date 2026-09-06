"""Shared status-line formatting for Rich footer and prompt_toolkit toolbar."""

from __future__ import annotations

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name
from kite.models.reasoning import reasoning_badge
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_SEP
from kite.ui.theme import glyph

_CONTEXT_BAR_WIDTH = 8


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
    return f"{spin} [{ts}] {label}  running"


def format_metrics_tail(state: SessionUiState) -> str:
    """Throughput, cache, context, and cost — always-on footer metrics."""
    parts: list[str] = []
    if state.busy or state.tps > 0:
        parts.append(f"{state.tps:.0f} tok/s" if state.tps > 0 else "— tok/s")
    if state.cache_hit_tokens > 0 or state.cache_hit_ratio > 0:
        parts.append(f"cache {state.cache_hit_ratio:.0%}")
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
    mode_label = "plan" if state.mode is AgentMode.PLAN else state.mode.value
    mode_bits = [mode_label, approval_display_name(state.approval)]
    if state.mode is AgentMode.PLAN and state.todos:
        done = sum(1 for t in state.todos if t.status == "completed")
        mode_bits.append(f"list {done}/{len(state.todos)}")
    if state.sandbox_restricted:
        mode_bits.append("restricted")
    parts = [*mode_bits, *status_context_parts(state)]
    return f" {SYMBOL_SEP} ".join(parts)


def approval_style(state: SessionUiState) -> str:
    if state.approval in {ApprovalMode.APPROVE, ApprovalMode.YOLO}:
        return "kite.pending" if state.approval is ApprovalMode.APPROVE else "kite.build"
    if state.approval is ApprovalMode.READONLY:
        return "kite.muted"
    return "kite.muted"


def mode_style(state: SessionUiState) -> str:
    return "kite.plan" if state.mode is AgentMode.PLAN else "kite.build"
