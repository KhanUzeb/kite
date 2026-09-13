"""Multi-line composer — Enter send, Alt+Enter newline (Pi-style)."""

from __future__ import annotations

from dataclasses import dataclass

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class Composer(TextArea):
    """Pi-style composer: plain Enter submits, Alt+Enter inserts a newline."""

    @dataclass
    class Submitted(Message):
        """Posted when the user sends the composer buffer."""

        composer: Composer
        text: str

        @property
        def control(self) -> Composer:
            return self.composer

    DEFAULT_CSS = """
    Composer {
        height: auto;
        min-height: 3;
        max-height: 10;
        border: tall $accent;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
            placeholder="Ask kite…  (Enter send · Alt+Enter newline · /help)",
            **kwargs,
        )

    async def _on_key(self, event: events.Key) -> None:
        if self.read_only:
            return
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            self._submit()
            return
        if key in {"alt+enter", "shift+enter"}:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)

    def _submit(self) -> None:
        text = self.text.strip()
        self.text = ""
        if text:
            self.post_message(self.Submitted(self, text))
