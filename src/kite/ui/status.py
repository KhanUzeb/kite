"""Shared status-line formatting for Rich footer and prompt_toolkit toolbar."""

from __future__ import annotations

from kite.agent.mode import AgentMode, ApprovalMode
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_SEP
from kite.ui.theme import glyph
from kite.models.reasoning import reasoning_badge

_CONTEXT_BAR_WIDTH = 8


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


def status_context_parts(state: SessionUiState) -> list[str]:
    """Model, context, cost — everything after mode and approval."""
    parts: list[str] = [format_model_label(state)]
    if state.reasoning and state.reasoning != "auto":
        parts.append(reasoning_badge(state.reasoning) or state.reasoning)
    if state.pending_attach:
        parts.append(f"+{state.pending_attach}")
    if state.active_subagents:
        parts.append(f"agents {state.active_subagents}")
    meter = context_meter(state.context_pct)
    if meter:
        parts.append(meter)
    elif state.tokens and state.window:
        parts.append(f"ctx {state.tokens}/{state.window}")
    if state.cache_hit_tokens > 0:
        parts.append(f"cache {state.cache_hit_ratio:.0%}")
    parts.append(f"${state.cost:.3f}")
    if state.git_branch:
        parts.append(state.git_branch)
    if state.interrupted:
        parts.append("interrupted")
    return parts


def format_status_tail(state: SessionUiState) -> str:
    """Everything after the kite brand — shared by render + composer toolbar."""
    mode_bits = [state.mode.value, state.approval.value]
    if state.sandbox_restricted:
        mode_bits.append("restricted")
    parts = [*mode_bits, *status_context_parts(state)]
    return f" {SYMBOL_SEP} ".join(parts)


def approval_style(state: SessionUiState) -> str:
    if state.approval is ApprovalMode.APPROVE:
        return "kite.pending"
    if state.approval is ApprovalMode.READONLY:
        return "kite.muted"
    return "kite.muted"


def mode_style(state: SessionUiState) -> str:
    return "kite.plan" if state.mode is AgentMode.PLAN else "kite.build"
