"""Small TTL cache for expensive discovery loads."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TtlCache(Generic[K, V]):
    """Monotonic-clock TTL cache with get-or-compute and optional LRU cap."""

    def __init__(self, ttl_seconds: float, maxsize: int = 32) -> None:
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.maxsize = max(1, maxsize)
        self._entries: dict[K, tuple[float, V]] = {}

    def _evict_if_needed(self, key: K) -> None:
        if key in self._entries or len(self._entries) < self.maxsize:
            return
        oldest_key = min(self._entries.items(), key=lambda item: item[1][0])[0]
        del self._entries[oldest_key]

    def get(self, key: K) -> V | None:
        cached = self._entries.get(key)
        if cached is None:
            return None
        if time.monotonic() - cached[0] >= self.ttl_seconds:
            del self._entries[key]
            return None
        return cached[1]

    def set(self, key: K, value: V) -> None:
        self._evict_if_needed(key)
        self._entries[key] = (time.monotonic(), value)

    def get_or_set(self, key: K, factory: Callable[[], V]) -> V:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value)
        return value

    def clear(self) -> None:
        self._entries.clear()
