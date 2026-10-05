"""Shared status-line formatting for Rich footer and prompt_toolkit toolbar."""

from __future__ import annotations

import shutil

from rich.text import Text

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_SEP
from kite.ui.theme import glyph

_CONTEXT_BAR_WIDTH = 8
_BRAND = "kite"

# Never truncate a field below this — a stub tells the reader nothing, and a
# second column of wrap is worse than an honest short field.
_MIN_FIELD_COLUMNS = 16


def terminal_width(default: int = 120) -> int:
    """Live terminal width — read fresh so windowed ↔ fullscreen resizes apply.

    Under Orca relay the reported pty width is not the phone width, so clamp
    to the relay tier (never as a desktop default).
    """
    from kite.util.tty import relay_width

    try:
        detected = max(40, int(shutil.get_terminal_size(fallback=(default, 24)).columns or default))
    except OSError:
        detected = default
    return relay_width(detected)


def _terminal_compact() -> bool:
    from kite.util.tty import is_orca_relay

    return True if is_orca_relay() else terminal_width() < 100


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
    width = terminal_width()
    label = state.running_label
    # Scale truncation to the live width: narrow windowed terminals clip
    # early so the line never wraps; wide fullscreen uses the full budget.
    label_limit = max(24, min(72, width - 52))
    if len(label) > label_limit:
        label = label[: max(1, label_limit - 1)] + "…"
    tick = int(time.monotonic() * 10)
    spin = loader_glyph("spin", tick)
    line = f"{spin} [{ts}] {label}  running"
    preview = sanitize_status_text(state.activity_preview)
    if preview:
        preview_limit = max(16, min(60, width - len(label) - 46))
        if len(preview) > preview_limit:
            preview = preview[: max(1, preview_limit - 1)] + "…"
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
    """provider/model with the thinking variant alongside (OpenCode #variant)."""
    if state.provider:
        base = f"{state.provider}/{state.model}"
    else:
        base = state.model or "—"
    badge = _variant_badge(state.reasoning)
    return f"{base}#{badge}" if badge else base


def _variant_badge(raw: str | None) -> str:
    """Compact Pi level for the status line — pure, no model metadata needed."""
    from kite.models.reasoning import split_reasoning

    mode, effort = split_reasoning(raw)
    if mode == "auto":
        return ""
    if effort and effort.lower() not in {"", "on"}:
        return effort.lower()
    return mode


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


def _short_error(text: str, limit: int = 64) -> str:
    flat = sanitize_status_text(text)
    if len(flat) > limit:
        return flat[: limit - 1] + "…"
    return flat


def status_context_parts(state: SessionUiState) -> list[str]:
    parts: list[str] = [format_model_label(state)]
    if state.pending_attach:
        parts.append(f"+{state.pending_attach}")
    if state.active_jobs:
        parts.append(f"jobs {state.active_jobs}")
    elif state.active_subagents:
        parts.append(f"agents {state.active_subagents}")
    if state.git_branch:
        branch = state.git_branch + ("*" if state.git_dirty > 0 else "")
        parts.append(branch)
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
    if state.last_error.strip() and not state.busy:
        parts.append(f"error: {_short_error(state.last_error)}")
    return parts


def _segment_style(text: str) -> str:
    if text.startswith("approve "):
        return "kite.pending"
    if text.startswith("error:"):
        return "kite.error"
    if text == "working":
        return "kite.highlight"
    if text.startswith("verify ") or text in _VERIFY_LABELS.values():
        return "kite.pending"
    return "kite.muted"


# What each status segment is worth when the row runs out of columns; lower is
# kept longer. The fields a user actually scans the footer for — mode, model,
# cost/context, error state, approval — must survive a 60-col window; the
# background-work counts are the ones worth losing.
_SEGMENT_RANK = {
    "mode": 0,
    "approval": 0,
    "label": 0,
    "error": 1,
    "model": 1,
    "cost": 2,
    "ctx": 3,
    "jobs": 4,
    "agents": 4,
}
# Rank at or below this is never dropped: without these the line no longer says
# what mode the agent is in or that it is waiting on the user.
_RANK_FLOOR = 2


def _sep_join() -> str:
    """One separator between segments, read live so /font stays live."""
    return f" {SYMBOL_SEP} "


def _segments_columns(parts: list[tuple[str, str, str]]) -> int:
    join = len(_sep_join())
    return sum(len(text) for text, _, _ in parts) + join * max(0, len(parts) - 1)


def _row_prefix_columns() -> int:
    """Columns the Rich footer spends on ``kite · `` before the first segment.

    ``format_status_tail`` is the same row without the brand and so has this
    much slack; budgeting to the wider consumer keeps both inside the window.
    """
    return len(_BRAND) + len(_sep_join())


def _shorten(text: str, limit: int) -> str:
    """Cut to ``limit`` columns with an explicit ellipsis — never a silent slice."""
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _fit_segments(
    parts: list[tuple[str, str, str]], *, width: int
) -> list[tuple[str, str, str]]:
    """Drop, then shorten, segments until the row fits ``width`` columns.

    Dropping is whole-segment only and stops at ``_RANK_FLOOR`` so the footer
    never degrades into a bare cost figure. Truncation is a last resort and
    stops at ``_MIN_FIELD_COLUMNS`` so a field stays recognisable instead of
    turning the row into two ragged rows.
    """
    budget = max(_MIN_FIELD_COLUMNS * 2, width - _row_prefix_columns())
    kept = list(parts)
    while len(kept) > 2 and _segments_columns(kept) > budget:
        # Worst = lowest rank, and among equals the rightmost (the newest
        # background count) so dropping is stable frame to frame.
        worst = max(range(len(kept)), key=lambda i: (_SEGMENT_RANK.get(kept[i][2], 9), i))
        if _SEGMENT_RANK.get(kept[worst][2], 9) <= _RANK_FLOOR:
            break
        kept.pop(worst)
    # Anything still over budget is shortened — longest first, and never below
    # _MIN_FIELD_COLUMNS, so a field stays recognisable rather than splitting
    # the row into two ragged ones.
    while _segments_columns(kept) > budget:
        optional = [
            i for i, (_, _, key) in enumerate(kept) if key not in {"mode", "approval", "label"}
        ]
        movable = [i for i in optional if len(kept[i][0]) > _MIN_FIELD_COLUMNS]
        if not movable:
            break
        target = max(movable, key=lambda i: len(kept[i][0]))
        text, style, key = kept[target]
        over = _segments_columns(kept) - budget
        kept[target] = (_shorten(text, len(text) - over), style, key)
    return kept


def _status_parts(state: SessionUiState) -> list[tuple[str, str, str]]:
    """(text, style, rank-key) segments after the brand, before width fitting."""
    if state.awaiting_approval:
        label = state.awaiting_approval or "tool"
        return [("approval", "kite.pending", "approval"), (label, "kite.pending", "label")]

    mode_label = "plan" if state.mode is AgentMode.PLAN else state.mode.value
    model = format_model_label(state)
    cost = f"${state.cost:.3f}"

    parts: list[tuple[str, str, str]] = [
        (mode_label, mode_style(state), "mode"),
        (model, "kite.muted", "model"),
        (cost, "kite.muted", "cost"),
    ]
    if not state.busy and state.window and state.tokens and not _terminal_compact():
        parts.append(
            (
                (
                    f"ctx {state.context_pct:.0%}"
                    if state.context_pct is not None
                    else f"{state.tokens} tok"
                ),
                "kite.muted",
                "ctx",
            )
        )
    if state.active_jobs:
        parts.append((f"{state.active_jobs} job{'s' if state.active_jobs != 1 else ''}", "kite.highlight", "jobs"))
    if state.active_subagents:
        parts.append((f"{state.active_subagents} agent{'s' if state.active_subagents != 1 else ''}", "kite.highlight", "agents"))
    if not state.busy and state.last_error.strip():
        parts.append((f"err {_short_error(state.last_error)}", "kite.error", "error"))
    return parts


def status_segments(state: SessionUiState) -> list[tuple[str, str]]:
    """Ordered (text, rich_style) segments shown after the kite brand.

    Width-aware: as the terminal narrows the optional segments go, then the
    long ones shorten, so the footer stays one row instead of wrapping.
    """
    parts = _fit_segments(_status_parts(state), width=terminal_width())
    return [(text, style) for text, style, _ in parts]


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
    return _sep_join().join(parts)


def render_status(state: SessionUiState) -> Text:
    """Rich status line — matches toolbar fields with semantic colors."""
    line = Text()
    line.append(_BRAND, style="kite.brand")
    for text, style in status_segments(state):
        line.append(_sep_join(), style="kite.muted")
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
