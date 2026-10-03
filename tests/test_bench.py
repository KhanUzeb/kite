"""Harness timing suite and budget regression gates."""

from __future__ import annotations

from kite.bench.budgets import BUDGETS_MS, check_report
from kite.bench.suite import load_report, run_suite, save_report


def _c_test_run_suite_budgets_and_violations(workspace) -> None:
    report = run_suite(cwd=workspace)
    names = {r.name for r in report.results}
    assert names == set(BUDGETS_MS)
    assert all(r.seconds >= 0 for r in report.results)
    for category in ("startup", "context", "tools"):
        assert [r for r in report.results if r.category == category], category
    violations = check_report(report)
    assert not violations, "\n".join(violations)


def _c_test_token_efficiency_offline_report() -> None:
    from kite.bench.token_efficiency import report

    rep = report()
    assert rep["tools_saved_tokens"] > 0 and rep["breakpoints"] == 2
    assert rep["total_core"] < rep["total_full"] and rep["ranked_sources"]


def _c_test_report_roundtrip(workspace, tmp_path) -> None:
    report = run_suite(cwd=workspace)
    path = tmp_path / "bench.json"
    save_report(report, path)
    loaded = load_report(path)
    assert len(loaded.results) == len(report.results)
    assert {r.name for r in loaded.results} == {r.name for r in report.results}


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_run_suite_budgets_and_violations, test_token_efficiency_offline_report, test_report_roundtrip."""
    _w0 = tmp_path / "w0_0"
    (_w0 / "src").mkdir(parents=True, exist_ok=True)
    (_w0 / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (_w0 / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _c_test_run_suite_budgets_and_violations(workspace=_w0)
    _c_test_token_efficiency_offline_report()
    _t2 = tmp_path / "t0_2"
    _t2.mkdir(parents=True, exist_ok=True)
    _w2 = tmp_path / "w0_2"
    (_w2 / "src").mkdir(parents=True, exist_ok=True)
    (_w2 / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (_w2 / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    _c_test_report_roundtrip(tmp_path=_t2, workspace=_w2)

