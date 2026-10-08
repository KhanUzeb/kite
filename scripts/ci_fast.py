#!/usr/bin/env python3
# kite-release-version: 1.0.6
"""Conservative changed-file pytest selection; unknown/shared changes run the full suite."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Deliberately broad domain sets. This is an inner loop, not a replacement for full CI.
DOMAIN_TESTS = {
    "bench": ("bench",),
    "ui": ("ui*", "composer", "repl_exit", "minimal_ux", "slash*", "sol_pi", "cli", "streaming"),
    "memory": ("memory*", "session*", "agent", "headless_tasks", "ui_retrieval"),
    "providers": ("provider*", "credentials", "auth*", "*oauth", "models", "onboarding", "cli", "headless_tasks"),
    "models": ("models", "provider*", "streaming", "agent", "headless_tasks", "*oauth"),
    "tools": ("tools", "search", "web*", "github", "parallel", "orchestrator", "security", "guardrails", "agent", "workspace"),
    "skills": ("skills", "cli", "ui", "security", "guardrails"),
}


def changed_paths(base: str) -> list[str]:
    tracked = subprocess.check_output(["git", "diff", "--name-only", "-z", base, "--"], cwd=ROOT)
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    return sorted({name.decode() for name in (tracked + untracked).split(b"\0") if name})


def select_tests(paths: list[str]) -> list[str]:
    selected: set[str] = set()
    for name in paths:
        path = Path(name)
        if name.startswith("tests/test_") and path.suffix == ".py" and (ROOT / path).is_file():
            selected.add(name)
        elif name.startswith("src/kite/bench/") or name == "src/kite/cli/bench.py":
            selected.add("tests/test_bench.py")
        elif name.startswith("src/kite/") and len(path.parts) > 3 and path.parts[2] in DOMAIN_TESTS:
            for pattern in DOMAIN_TESTS[path.parts[2]]:
                selected.update(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob(f"test_{pattern}.py"))
        elif path.suffix in {".md", ".rst", ".txt", ".png", ".svg"} and not name.startswith("src/"):
            continue
        else:
            return ["tests"]
    return sorted(selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--base", default="HEAD", help="Git revision to diff against (default: HEAD, plus untracked files)")
    source.add_argument("--files", nargs="+", help="Explicit repository-relative changed paths")
    parser.add_argument("--list", action="store_true", help="Print selection JSON without running any gates")
    args = parser.parse_args()
    paths = args.files if args.files is not None else changed_paths(args.base)
    tests = select_tests(paths)
    lint = sorted(name for name in paths if name.endswith(".py") and (ROOT / name).is_file())
    if "tests" in tests:
        lint = ["src", "tests", "scripts"]
    selection = {"changed": paths, "lint": lint, "tests": tests, "full_fallback": tests == ["tests"]}
    print(json.dumps(selection, indent=2), flush=True)
    if args.list:
        return 0
    for label, command in (
        ("ruff (changed files)", [sys.executable, "-m", "ruff", "check", *lint] if lint else []),
        ("pytest (mapped modules)", [sys.executable, "-m", "pytest", "-q", "--tb=short", *tests] if tests else []),
    ):
        if not command:
            print(f"== {label}: no selected files", flush=True)
            continue
        print(f"== {label}", flush=True)
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT)
        print(f"== {label}: {time.perf_counter() - started:.2f}s", flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
