"""Opencode-style clarifying questions — asked live, mid-turn.

The harness calls the injected ``ask_user`` handler when the model uses the
``question`` tool. Each question shows its options numbered; the user picks
by number (comma-separated when multiple), types free text, or hits Enter
to take the recommended option (or skip when none set). A per-question
``timeout`` auto-picks the recommended option (or skips) on expiry.
EOF skips the rest; KeyboardInterrupt propagates so Esc/Ctrl-C
still stops the turn.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console

RECOMMENDED_SUFFIX = " (Recommended)"


def _resolve_recommended(options: list[dict[str, Any]], recommended: Any) -> str:
    """Match a recommended label to an option label (suffix-tolerant)."""
    want = str(recommended or "").strip()
    if not want:
        return ""
    labels = [str(o.get("label") or "").strip() for o in options]
    if want in labels:
        return want
    suffixed = want + RECOMMENDED_SUFFIX
    if suffixed in labels:
        return suffixed
    return ""


def _display_label(label: str, recommended_label: str) -> str:
    """Append the recommended suffix once (never doubled)."""
    if label and label == recommended_label and not label.endswith(RECOMMENDED_SUFFIX):
        return label + RECOMMENDED_SUFFIX
    return label


def _coerce_timeout(value: Any) -> float | None:
    """Per-question timeout in seconds; None when unset/invalid.

    Zero or negative means already expired (auto-answer without blocking).
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return None
    return seconds


def _read_with_timeout(
    console: Console, prompt: str, timeout_s: float
) -> tuple[str | None, bool]:
    """Read one line; on expiry return (None, True) instead of blocking.

    EOFError propagates so the caller can skip the rest; KeyboardInterrupt
    propagates so Esc/Ctrl-C still stops the turn. Cross-platform: a daemon
    input thread plus join(timeout) — no select() on stdin.
    """
    from kite.ui.pick import _read_choice

    outcome: dict[str, Any] = {}

    def _worker() -> None:
        try:
            outcome["line"] = _read_choice(console, prompt)
        except BaseException as exc:  # EOF travels back to the caller
            outcome["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        return None, True
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("line", ""), False


def ask_user_questions(
    console: Console, questions: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Prompt every question; return aligned [{answer, options}] or None on EOF."""
    from kite.ui.pick import _read_choice

    answers: list[dict[str, Any]] = []
    total = len(questions)
    for idx, item in enumerate(questions):
        header = str(item.get("header") or "").strip()
        text = str(item.get("question") or "").strip()
        options = [o for o in (item.get("options") or []) if isinstance(o, dict)]
        multiple = bool(item.get("multiple"))
        recommended = _resolve_recommended(options, item.get("recommended"))
        timeout_s = _coerce_timeout(item.get("timeout"))
        title = f"question {idx + 1}/{total}" + (f" · {header}" if header else "")
        console.print(f"[kite.brand]{title}[/]  {text}")
        for num, opt in enumerate(options, start=1):
            label = str(opt.get("label") or "").strip()
            desc = str(opt.get("description") or "").strip()
            shown = _display_label(label, recommended)
            suffix = f" — {desc}" if desc else ""
            console.print(f"[kite.pick]{num:>3}  {shown}[/][kite.muted]{suffix}[/]")
        hint = "number · text · empty skip"
        if multiple:
            hint += " · comma for several"
        prompt = f"Pick {hint}"
        if timeout_s is not None:
            auto = f"auto-picks {recommended}" if recommended else "auto-skips"
            prompt += f" ({auto} in {timeout_s:g}s)"
        prompt += ": "
        raw = ""
        timed_out = False
        try:
            if timeout_s is not None and timeout_s <= 0:
                timed_out = True  # already expired — never block on input
            elif timeout_s is not None:
                line, timed_out = _read_with_timeout(console, prompt, timeout_s)
                raw = line or ""
            else:
                raw = _read_choice(console, prompt)
        except EOFError:
            return None
        if timed_out:
            raw = ""
        answer, picked = _interpret_answer(
            raw, options, multiple=multiple, recommended=recommended
        )
        answers.append({"answer": answer, "options": picked})
    return answers


def _interpret_answer(
    raw: str,
    options: list[dict[str, Any]],
    *,
    multiple: bool,
    recommended: Any = None,
) -> tuple[str, list[str]]:
    """Numbers (comma-separated when multiple) → labels, else free text.

    Bare Enter picks the recommended option when set, else skips. A typed
    suffixed display label ("blue (Recommended)") maps back to its option.
    """
    labels = [str(o.get("label") or "").strip() for o in options]
    recommended_label = _resolve_recommended(options, recommended)
    display = {_display_label(label, recommended_label): label for label in labels}
    tokens = [tok.strip() for tok in raw.split(",") if tok.strip()]
    if tokens and all(tok.isdigit() for tok in tokens):
        idxs = [int(tok) for tok in tokens]
        if not multiple:
            idxs = idxs[:1]
        picked = [labels[i - 1] for i in idxs if 1 <= i <= len(labels)]
        if picked:
            joined = ", ".join(picked)
            return joined, picked
    text = raw.strip()
    if text:
        if text in display:
            label = display[text]
            return label, [label]
        return text, []
    if recommended_label:
        return recommended_label, [recommended_label]
    return "", []
