"""Monotonic timing helpers for repeatable micro-benchmarks."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TimingSample:
    name: str
    seconds: float
    iterations: int = 1

    @property
    def ms(self) -> float:
        return self.seconds * 1000.0


def measure(name: str, fn: Callable[[], T], *, iterations: int = 1) -> tuple[T, TimingSample]:
    """Run *fn* once or many times; return value and wall-time sample."""
    n = max(1, iterations)
    start = time.perf_counter()
    result = fn()
    for _ in range(n - 1):
        fn()
    elapsed = time.perf_counter() - start
    return result, TimingSample(name=name, seconds=elapsed / n, iterations=n)


def measure_many(name: str, fn: Callable[[], T], *, iterations: int = 5) -> tuple[T, TimingSample]:
    """Run *fn* *iterations* times and return median wall time."""
    n = max(1, iterations)
    samples: list[float] = []
    result: T | None = None
    for _ in range(n):
        start = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)
    return result, TimingSample(name=name, seconds=median, iterations=n)
