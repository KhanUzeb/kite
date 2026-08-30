"""TTL cache utility."""

from __future__ import annotations

import time

from kite.util.cache import TtlCache


def test_ttl_cache_hit_returns_same_object() -> None:
    cache: TtlCache[str, list[int]] = TtlCache(60.0)
    first = cache.get_or_set("k", lambda: [1])
    second = cache.get_or_set("k", lambda: [2])
    assert first is second
    assert first == [1]


def test_ttl_cache_expires() -> None:
    cache: TtlCache[str, str] = TtlCache(0.01)
    first = cache.get_or_set("k", lambda: "a")
    time.sleep(0.02)
    second = cache.get_or_set("k", lambda: "b")
    assert first == "a"
    assert second == "b"
