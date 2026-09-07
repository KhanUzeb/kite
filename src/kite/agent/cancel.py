"""Shared cancellation token for model streams and long-running tools."""

from __future__ import annotations

import threading


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()
