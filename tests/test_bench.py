"""Benchmark suite tests — no live LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kite.bench.suite import BenchmarkReport, BenchmarkResult, load_report, run_suite, save_report
from kite.bench.timing import measure, measure_many


def test_measure_runs_fn(workspace: Path):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 42

    value, sample = measure("demo", fn, iterations=3)
    assert value == 42
    assert calls["n"] == 3
    assert sample.name == "demo"
    assert sample.seconds >= 0


def test_measure_many_returns_median(workspace: Path):
    _, sample = measure_many("demo", lambda: None, iterations=3)
    assert sample.iterations == 3
    assert sample.seconds >= 0


def test_run_suite_produces_results(workspace: Path):
    report = run_suite(cwd=workspace)
    assert isinstance(report, BenchmarkReport)
    assert report.results
    names = {r.name for r in report.results}
    assert "read_tool" in names
    assert "context_gather" in names
    for row in report.results:
        assert row.seconds >= 0
        assert row.category


def test_report_roundtrip(workspace: Path, tmp_path: Path):
    report = run_suite(cwd=workspace)
    path = tmp_path / "bench.json"
    save_report(report, path)
    loaded = load_report(path)
    assert loaded.kite_version == report.kite_version
    assert len(loaded.results) == len(report.results)
    assert loaded.results[0].name == report.results[0].name


def test_compare_delta(workspace: Path):
    before = BenchmarkReport(
        kite_version="0.0.0",
        python_version="3.11",
        platform="test",
        cwd=str(workspace),
        results=(
            BenchmarkResult("read_tool", "tools", 0.010, iterations=1),
            BenchmarkResult("grep_tool", "tools", 0.020, iterations=1),
        ),
    )
    after = BenchmarkReport(
        kite_version="0.0.1",
        python_version="3.11",
        platform="test",
        cwd=str(workspace),
        results=(
            BenchmarkResult("read_tool", "tools", 0.008, iterations=1),
            BenchmarkResult("grep_tool", "tools", 0.025, iterations=1),
        ),
    )
    rows = after.compare(before)
    by_name = {r["name"]: r for r in rows}
    assert by_name["read_tool"]["delta_ms"] == pytest.approx(-2.0, abs=0.01)
    assert by_name["grep_tool"]["delta_ms"] == pytest.approx(5.0, abs=0.01)


def test_cmd_bench_json(workspace: Path, capsys):
    import argparse

    from kite.cli.bench import cmd_bench

    rc = cmd_bench(argparse.Namespace(cwd=str(workspace), json=True, save=None, compare=None))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "results" in payload
    assert payload["results"]
