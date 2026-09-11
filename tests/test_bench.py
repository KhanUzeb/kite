"""Harness timing suite and budget regression gates."""

from __future__ import annotations

from kite.bench.budgets import BUDGETS_MS, check_report
from kite.bench.suite import load_report, run_suite, save_report


def test_run_suite_includes_all_budgeted_benchmarks(workspace) -> None:
    report = run_suite(cwd=workspace)
    names = {r.name for r in report.results}
    assert names == set(BUDGETS_MS)
    assert all(r.seconds >= 0 for r in report.results)
    for category in ("startup", "context", "tools"):
        assert [r for r in report.results if r.category == category], category


def test_harness_benchmarks_within_budget(workspace) -> None:
    report = run_suite(cwd=workspace)
    violations = check_report(report)
    assert not violations, "\n".join(violations)


def test_report_roundtrip(workspace, tmp_path) -> None:
    report = run_suite(cwd=workspace)
    path = tmp_path / "bench.json"
    save_report(report, path)
    loaded = load_report(path)
    assert len(loaded.results) == len(report.results)
    assert {r.name for r in loaded.results} == {r.name for r in report.results}


def test_repl_startup_banner_skips_model_resolve(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def _fake_resolve(**_kwargs):
        calls.append("resolve")
        raise AssertionError("resolve_model should not run during startup banner")

    monkeypatch.setattr("kite.providers.resolve.resolve_model", _fake_resolve)
    from kite.ui.repl import ChatSession

    ChatSession(cwd=str(tmp_path))._startup_banner()
    assert not calls
