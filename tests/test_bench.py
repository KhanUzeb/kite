"""Harness timing suite and budget regression gates."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

import pytest

from kite.bench.budgets import BUDGETS_MS, check_report
from kite.bench.suite import BenchmarkReport, BenchmarkResult, load_report, run_suite, save_report


@pytest.fixture(autouse=True)
def _isolate_benchmark_environment(kite_home, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("kite.context.toolchains.scout_toolchains", lambda *_args: [])


def test_run_suite_uses_disposable_workspace(workspace, monkeypatch) -> None:
    from kite.bench.timing import TimingSample
    from kite.config import UserConfig

    # Execute each operation once; wall-clock performance belongs to `kite bench --check`.
    def measure_once(name, operation, *, iterations=1):
        return operation(), TimingSample(name, 0.001, 1, (0.001,))

    monkeypatch.setattr("kite.bench.suite.measure", measure_once)
    monkeypatch.setattr("kite.bench.suite.measure_many", measure_once)
    UserConfig(default_provider="ollama", default_model="bench-offline").save()
    empty = workspace / "untouched"
    empty.mkdir()
    report = run_suite(cwd=empty)
    assert not list(empty.iterdir()), "benchmark fixtures must not be created in the user's workspace"
    assert report.cwd == str(empty.resolve())
    results = {result.name: result for result in report.results}
    assert results["read_tool"].metadata["ok"] is True
    assert results["grep_tool"].metadata["ok"] is True
    assert results["bash_echo"].metadata["ok"] is True
    assert results["checkpoint_roundtrip"].metadata["roundtrip"] is True
    assert not check_report(report)


def test_budget_boundaries_missing_measurements_and_operation_failures() -> None:
    results = tuple(
        BenchmarkResult(name, "tools", ceiling / 1000)
        for name, ceiling in BUDGETS_MS.items()
    )
    report = BenchmarkReport("test", "3.12.0", "test-platform", "fixture", results)
    assert check_report(report) == []
    over = replace(results[0], seconds=results[0].seconds + 0.001)
    assert any("budget" in violation for violation in check_report(replace(report, results=(over, *results[1:]))))
    assert check_report(replace(report, results=results[1:])) == [f"missing benchmark '{results[0].name}' in report"]
    unknown = BenchmarkResult("unknown", "tools", 0)
    assert check_report(replace(report, results=(*results, unknown))) == ["missing budget for benchmark 'unknown'"]
    for metadata in ({"ok": False}, {"roundtrip": False}, {"returncode": 1}):
        failed = replace(results[0], metadata=metadata)
        assert check_report(replace(report, results=(failed, *results[1:]))) == [
            f"{failed.name}: benchmark operation failed"
        ]


def test_token_efficiency_offline_report() -> None:
    from kite.bench.token_efficiency import report

    rep = report()
    assert rep["tools_saved_tokens"] > 0
    assert rep["total_core"] < rep["total_full"] and rep["ranked_sources"]


def test_report_roundtrip(workspace, tmp_path) -> None:
    report = BenchmarkReport("test", "3.12.0", "test-platform", str(workspace), (
        BenchmarkResult("example", "startup", 0.01, 5, {"mad_ms": 0.5}),
    ))
    path = tmp_path / "bench.json"
    save_report(report, path)
    loaded = load_report(path)
    assert loaded == report


def test_noise_aware_comparison_and_cli(tmp_path, monkeypatch, capsys) -> None:
    from kite.cli.bench import add_bench_parser

    baseline = BenchmarkReport("test", "3.12.0", "test-platform", "fixture", (
        BenchmarkResult("steady", "startup", 0.010, 5, {"mad_ms": 0.1}),
        BenchmarkResult("noisy", "startup", 0.010, 5, {"mad_ms": 2.0}),
        BenchmarkResult("tiny", "startup", 0.0001, 5),
    ))
    current = replace(baseline, results=(
        replace(baseline.results[0], seconds=0.015),
        replace(baseline.results[1], seconds=0.015),
        replace(baseline.results[2], seconds=0.0003),
    ))
    rows = current.compare(baseline)
    assert [row["regression"] for row in rows] == [True, False, False]
    assert rows[0]["delta_pct"] == 50.0
    assert not current.compare(baseline, threshold_pct=60)[0]["regression"]
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    save_report(baseline, before)
    monkeypatch.setattr("kite.bench.suite.run_suite", lambda **_: current)
    parser = argparse.ArgumentParser()
    add_bench_parser(parser.add_subparsers())
    args = parser.parse_args(["bench", "--compare", str(before), "--save", str(after), "--json"])
    assert args.func(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["compare"][0]["regression"] and after.is_file()
    assert load_report(after) == current
    args.threshold = 60
    assert args.func(args) == 0
    capsys.readouterr()
    save_report(replace(baseline, results=()), before)
    assert args.func(args) == 1
    assert json.loads(capsys.readouterr().out)["comparison_errors"]
    before.unlink()
    assert args.func(args) == 2
    assert "Cannot load benchmark baseline" in capsys.readouterr().err


