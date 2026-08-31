"""Lightweight harness benchmarks — repeatable timing without live LLM calls."""

from kite.bench.suite import BenchmarkReport, BenchmarkResult, run_suite
from kite.bench.timing import measure, measure_many

__all__ = [
    "BenchmarkReport",
    "BenchmarkResult",
    "measure",
    "measure_many",
    "run_suite",
]
