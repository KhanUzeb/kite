"""Opencode-style clarifying questions — asked live, mid-turn.

The harness calls the injected ``ask_user`` handler when the model uses the
``question`` tool. Each question shows its options numbered; the user picks
by number (comma-separated when multiple), types free text, or hits Enter
to skip. EOF skips the rest; KeyboardInterrupt propagates so Esc/Ctrl-C
still stops the turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console


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
        title = f"question {idx + 1}/{total}" + (f" · {header}" if header else "")
        console.print(f"[kite.brand]{title}[/]  {text}")
        for num, opt in enumerate(options, start=1):
            label = str(opt.get("label") or "").strip()
            desc = str(opt.get("description") or "").strip()
            suffix = f" — {desc}" if desc else ""
            console.print(f"[kite.pick]{num:>3}  {label}[/][kite.muted]{suffix}[/]")
        hint = "numbers" + (", comma for several" if multiple else "") + ", text, or empty to skip"
        try:
            raw = _read_choice(console, f"Pick {hint}: ")
        except EOFError:
            return None
        answer, picked = _interpret_answer(raw, options, multiple=multiple)
        answers.append({"answer": answer, "options": picked})
    return answers


def _interpret_answer(
    raw: str, options: list[dict[str, Any]], *, multiple: bool
) -> tuple[str, list[str]]:
    """Numbers (comma-separated when multiple) → labels, else free text."""
    labels = [str(o.get("label") or "").strip() for o in options]
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
        return text, []
    return "", []
