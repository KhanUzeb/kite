"""`kite bench` — repeatable harness timing without live LLM calls."""

from __future__ import annotations

import argparse
import json
import sys

from kite.bench.suite import BenchmarkReport, load_report, run_suite, save_report


def _print_table(report: BenchmarkReport) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    console.print(f"[bold]Kite harness benchmark[/]  v{report.kite_version}  ({report.platform})")
    console.print(f"cwd: {report.cwd}\n")
    console.print(f"{'name':<22} {'category':<10} {'ms':>10}  {'iters':>5}")
    console.print("-" * 52)
    for row in report.results:
        console.print(f"{row.name:<22} {row.category:<10} {row.ms:>10.1f}  {row.iterations:>5}")


def _print_compare(current: BenchmarkReport, baseline: BenchmarkReport) -> None:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    rows = current.compare(baseline)
    console.print("[bold]BEFORE → AFTER (DELTA)[/]\n")
    console.print(f"{'name':<22} {'before':>10} {'after':>10} {'delta':>10} {'%':>8}")
    console.print("-" * 64)
    for row in rows:
        sign = "+" if row["delta_ms"] >= 0 else ""
        console.print(
            f"{row['name']:<22} {row['before_ms']:>10.1f} {row['after_ms']:>10.1f} "
            f"{sign}{row['delta_ms']:>9.1f} {row['delta_pct']:>7.1f}%"
        )


def cmd_bench(args: argparse.Namespace) -> int:
    report = run_suite(cwd=args.cwd)

    if args.compare:
        baseline = load_report(args.compare)
        if args.json:
            print(json.dumps({"current": report.to_dict(), "compare": report.compare(baseline)}, indent=2))
        else:
            _print_compare(report, baseline)
        return 0

    if args.save:
        save_report(report, args.save)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    _print_table(report)
    if args.save:
        print(f"\nSaved: {args.save}", file=sys.stderr)
    return 0


def add_bench_parser(sub) -> None:
    bench = sub.add_parser("bench", help="Measure harness startup/context/tool latency (no LLM)")
    bench.add_argument("--cwd", default=None, help="Workspace for tool benchmarks (default: cwd)")
    bench.add_argument("--json", action="store_true", help="Emit JSON report on stdout")
    bench.add_argument("--save", metavar="PATH", help="Write JSON report to PATH")
    bench.add_argument(
        "--compare",
        metavar="BASELINE.json",
        help="Compare against a saved baseline (BEFORE/AFTER/DELTA table)",
    )
    bench.set_defaults(func=cmd_bench)
