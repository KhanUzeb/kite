"""Shared cancellation token for model streams and long-running tools."""

from __future__ import annotations


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def request(self) -> None:
        self._cancelled = True

    def is_set(self) -> bool:
        return self._cancelled

    def reset(self) -> None:
        self._cancelled = False
