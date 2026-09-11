"""Plain completion rows for the Textual composer (no prompt_toolkit)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from kite.cli.slash import CommandIndex
from kite.models.reasoning import ReasoningSupport
from kite.ui.complete import SlashCompleter


@dataclass(frozen=True)
class PlainCompletion:
    insert: str
    display: str
    meta: str
    replace_chars: int


class _FakeDocument:
    text_before_cursor: str

    def __init__(self, text: str) -> None:
        self.text_before_cursor = text


def plain_completions(
    text_before_cursor: str,
    *,
    index_factory: Callable[[], CommandIndex],
    models_factory: Callable[[], Iterable[str]] | None = None,
    providers_factory: Callable[[], Iterable[str]] | None = None,
    reasoning_info: Callable[[], ReasoningSupport | None] | None = None,
    limit: int = 20,
) -> list[PlainCompletion]:
    """Slash and @file suggestions for a composer line prefix."""
    completer = SlashCompleter(
        index_factory,
        models_factory=models_factory,
        providers_factory=providers_factory,
        reasoning_info=reasoning_info,
    )
    doc = _FakeDocument(text_before_cursor)
    rows: list[PlainCompletion] = []
    for item in completer.get_completions(doc, None):
        replace = abs(int(item.start_position)) if item.start_position else 0
        display = _completion_display(item.display)
        meta = _completion_display(item.display_meta)
        rows.append(
            PlainCompletion(
                insert=str(item.text),
                display=display or str(item.text),
                meta=meta,
                replace_chars=replace,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _completion_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # prompt_toolkit FormattedText / HTML — take plain text chunks
    try:
        return "".join(part[1] for part in value)
    except Exception:
        return str(value)
