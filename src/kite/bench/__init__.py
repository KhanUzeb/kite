"""Lightweight harness benchmarks — repeatable timing without live LLM calls."""

from kite.bench.budgets import BUDGETS_MS, CATEGORIES, check_report
from kite.bench.suite import BenchmarkReport, BenchmarkResult, run_suite
from kite.bench.timing import measure, measure_many

__all__ = [
    "BUDGETS_MS",
    "CATEGORIES",
    "BenchmarkReport",
    "BenchmarkResult",
    "check_report",
    "measure",
    "measure_many",
    "run_suite",
]

__all__ = [
    "BenchmarkReport",
    "BenchmarkResult",
    "measure",
    "measure_many",
    "run_suite",
]
