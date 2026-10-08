#!/usr/bin/env python3
# kite-release-version: 1.0.6
"""Profile the real CLI in-process; use cold_cli_help for interpreter/process startup cost."""

from __future__ import annotations

import argparse
import cProfile
import os
import runpy
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="cProfile pstats destination (local paths, no prompt content)")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="CLI arguments after --, e.g. -- bench --suite full")
    args = parser.parse_args()
    cli_args = args.args[1:] if args.args[:1] == ["--"] else args.args
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kite-profile-home-") as home:
        os.environ.setdefault("KITE_HOME", home)
        os.environ.setdefault("KITE_SKIP_SETUP", "1")
        os.environ.setdefault("KITE_TYPED_PICK", "1")
        sys.argv = ["kite", *cli_args]
        profiler = cProfile.Profile()
        try:
            profiler.enable()
            runpy.run_module("kite.cli.run", run_name="__main__")
        finally:
            profiler.disable()
            profiler.dump_stats(str(args.output))
            print(f"Profile: {args.output.resolve()} (main thread; excludes subprocess CPU)", file=sys.stderr)
            print(f"Inspect: python -m pstats {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
