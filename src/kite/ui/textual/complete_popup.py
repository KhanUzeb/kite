"""Slash / @file completion dropdown above the Textual composer."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static

from kite.ui.textual.complete_data import PlainCompletion


class CompletePopup(Vertical):
    """Floating completion menu — hidden when empty."""

    DEFAULT_CSS = """
    CompletePopup {
        height: auto;
        max-height: 10;
        border: solid $accent;
        background: $surface;
        display: none;
    }
    CompletePopup.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows: list[PlainCompletion] = []

    def compose(self):
        yield Static("", id="complete-title")
        yield OptionList(id="complete-options")

    def set_suggestions(self, rows: list[PlainCompletion]) -> None:
        self._rows = rows
        options = self.query_one("#complete-options", OptionList)
        title = self.query_one("#complete-title", Static)
        if not rows:
            options.clear_options()
            title.update("")
            self.remove_class("visible")
            return
        title.update("[dim]/ slash · @file[/]")
        options.clear_options()
        labels = []
        for row in rows:
            label = row.display
            if row.meta:
                label = f"{row.display}  [dim]{row.meta}[/]"
            labels.append(label)
        options.add_options(labels)
        self.add_class("visible")

    def hide(self) -> None:
        self.set_suggestions([])

    def selected(self) -> PlainCompletion | None:
        options = self.query_one("#complete-options", OptionList)
        idx = options.highlighted
        if idx is None or idx < 0 or idx >= len(self._rows):
            return None
        return self._rows[idx]

    @on(OptionList.OptionSelected, "#complete-options")
    def _pick(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.post_message(self.Picked(self, self.selected()))

    @dataclass
    class Picked(Message):
        popup: CompletePopup
        row: PlainCompletion | None

        @property
        def control(self) -> CompletePopup:
            return self.popup
