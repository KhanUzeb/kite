"""`kite bench` — repeatable harness timing without live LLM calls."""

from __future__ import annotations

import argparse
import json
import sys


def _print_table(report) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    console.print(f"[bold]Kite harness benchmark[/]  v{report.kite_version}  ({report.platform})")
    console.print(f"cwd: {report.cwd}\n")
    console.print(f"{'name':<22} {'category':<12} {'ms':>10}  {'iters':>5}")
    console.print("-" * 54)
    for row in report.results:
        console.print(f"{row.name:<22} {row.category:<12} {row.ms:>10.1f}  {row.iterations:>5}")


def _print_compare(rows) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    console.print("[bold]BEFORE → AFTER (DELTA)[/]\n")
    console.print(f"{'name':<22} {'before':>10} {'after':>10} {'delta':>10} {'%':>8}  status")
    console.print("-" * 64)
    for row in rows:
        sign = "+" if row["delta_ms"] >= 0 else ""
        console.print(
            f"{row['name']:<22} {row['before_ms']:>10.1f} {row['after_ms']:>10.1f} "
            f"{sign}{row['delta_ms']:>9.1f} {row['delta_pct']:>7.1f}%  "
            f"{'REGRESSION' if row['regression'] else 'ok'}"
        )


def _print_ab(report) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    console.print(f"[bold]Task / subagent A/B[/]  ({report.platform})")
    console.print(f"cwd: {report.cwd}\n")
    console.print(f"{'comparison':<22} {'A':<14} {'B':<14} {'Δms':>8} {'Δheap':>8} {'winner':<10}")
    console.print("-" * 78)
    for row in report.comparisons:
        sign = "+" if row.delta_ms >= 0 else ""
        console.print(
            f"{row.name:<22} {row.a_ms:>6.1f}ms {row.b_ms:>6.1f}ms "
            f"{sign}{row.delta_ms:>7.1f} {row.delta_peak_kb:>+7.1f}K {row.winner:<10}"
        )
    console.print("\n[bold]variants[/]  wall_ms · peak_kb (median)")
    for m in report.metrics:
        console.print(f"  {m.name:<12} {m.variant:<14} {m.wall_ms:>8.1f}ms  {m.peak_kb:>8.1f}KB")


def _print_stress(report) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    status = "PASS" if report.passed else "FAIL"
    console.print(f"[bold]Harness stress[/]  {status}  ({report.platform})")
    console.print(f"cwd: {report.cwd}\n")
    console.print(f"{'name':<28} {'iters':>6} {'median':>10} {'p95':>10} {'peak':>10} {'err':>5}")
    console.print("-" * 72)
    for row in report.results:
        console.print(
            f"{row.name:<28} {row.iterations:>6} {row.median_ms:>9.1f}ms "
            f"{row.p95_ms:>9.1f}ms {row.peak_kb:>9.1f}KB {row.errors:>5}"
        )
    if report.notes:
        console.print("\n[bold]notes[/]")
        for note in report.notes:
            console.print(f"  · {note}")


def cmd_bench(args: argparse.Namespace) -> int:
    from kite.bench.budgets import check_report
    from kite.bench.suite import load_report, run_suite, save_report

    if args.threshold < 0 or args.min_delta < 0:
        print("Comparison thresholds must be nonnegative.", file=sys.stderr)
        return 2
    if (args.ab or args.stress) and (args.compare or args.suite != "quick" or args.check):
        print("--ab/--stress cannot combine with --compare, --suite full or --check.", file=sys.stderr)
        return 2
    baseline = None
    if args.compare:
        try:
            baseline = load_report(args.compare)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Cannot load benchmark baseline: {exc}", file=sys.stderr)
            return 2
    if args.ab:
        from kite.bench.orchestrate_ab import run_orchestrate_ab

        report = run_orchestrate_ab(cwd=args.cwd, iterations=args.iterations)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            _print_ab(report)
        if args.save:
            from pathlib import Path

            Path(args.save).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        return 0

    if args.stress:
        from kite.bench.stress import run_stress_suite

        report = run_stress_suite(cwd=args.cwd)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            _print_stress(report)
        if args.save:
            from pathlib import Path

            Path(args.save).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        return 0 if report.passed else 1

    report = run_suite(cwd=args.cwd, suite=args.suite)
    violations = check_report(report) if args.check else []

    if args.save:
        save_report(report, args.save)

    if baseline is not None:
        rows = report.compare(baseline, threshold_pct=args.threshold, min_delta_ms=args.min_delta)
        current_names = {r.name for r in report.results}
        baseline_names = {r.name for r in baseline.results}
        comparison_errors = []
        if current_names != baseline_names:
            comparison_errors.append("Benchmark names differ; compare reports from the same suite.")
        if (report.platform != baseline.platform
                or report.python_version.split(".")[:2] != baseline.python_version.split(".")[:2]
                or report.cwd != baseline.cwd):
            comparison_errors.append("Platform, Python minor version or workspace differs from baseline.")
        failed = bool(violations or comparison_errors or any(row["regression"] for row in rows))
        if args.json:
            print(json.dumps({"current": report.to_dict(), "compare": rows,
                              "comparison_errors": comparison_errors, "budget_violations": violations}, indent=2))
        else:
            _print_compare(rows)
            for line in [*comparison_errors, *violations]:
                print(line, file=sys.stderr)
        return 1 if failed else 0

    if args.json:
        payload = report.to_dict()
        if violations:
            payload["budget_violations"] = violations
        print(json.dumps(payload, indent=2))
        return 1 if violations else 0

    _print_table(report)
    if args.save:
        print(f"\nSaved: {args.save}", file=sys.stderr)
    if violations:
        for line in violations:
            print(line, file=sys.stderr)
        return 1
    if args.check:
        print("All harness benchmarks within budget.", file=sys.stderr)
    return 0


def add_bench_parser(sub) -> None:
    bench = sub.add_parser("bench", help="Measure harness startup/context/tool latency (no LLM)")
    bench.add_argument("--cwd", default=None, help="Context workspace (default: generated fixture; never modified)")
    bench.add_argument("--suite", choices=("quick", "full"), default="quick",
                       help="full adds cold processes, streaming, agent turns and a generated 20k-file workspace")
    bench.add_argument("--threshold", type=float, default=20.0, metavar="PERCENT",
                       help="Comparison regression threshold (default: 20%%, also bounded by measured noise)")
    bench.add_argument("--min-delta", type=float, default=2.0, metavar="MS",
                       help="Minimum meaningful comparison delta in milliseconds (default: 2)")
    bench.add_argument("--json", action="store_true", help="Emit JSON report on stdout")
    bench.add_argument("--save", metavar="PATH", help="Write JSON report to PATH")
    bench.add_argument(
        "--compare",
        metavar="BASELINE.json",
        help="Compare a saved baseline; exit 1 for noise-adjusted regressions or incompatible reports",
    )
    bench.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any benchmark exceeds the harness timing budget",
    )
    bench.add_argument(
        "--ab",
        action="store_true",
        help="A/B test task vs subagent dispatch paths (time + peak heap)",
    )
    bench.add_argument(
        "--stress",
        action="store_true",
        help="Brute-force orchestrator stress test (time + space soft ceilings)",
    )
    bench.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Iterations per A/B variant (default 5)",
    )
    bench.set_defaults(func=cmd_bench)
