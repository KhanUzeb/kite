"""Textual message types for the Kite app."""

from __future__ import annotations

from typing import Any

from textual.message import Message


class AgentEventMessage(Message):
    """Agent harness event — handled on the UI thread."""

    def __init__(self, event: Any) -> None:
        super().__init__()
        self.event = event


class StatusFlashMessage(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
