"""Infer canonical test/verify commands from CI workflows (evidence over guesses)."""

from __future__ import annotations

import re
from pathlib import Path

# First match wins — ordered from most specific repo signals to generic.
_RUN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpytest\b[^|\n]*", re.IGNORECASE), "pytest"),
    (re.compile(r"\./scripts/ci_check\.sh\b"), "./scripts/ci_check.sh"),
    (re.compile(r"\bpnpm\s+(?:run\s+)?test\b"), "pnpm test"),
    (re.compile(r"\byarn\s+test\b"), "yarn test"),
    (re.compile(r"\bnpm\s+(?:run\s+)?test\b"), "npm test"),
    (re.compile(r"\bcargo\s+test\b"), "cargo test"),
    (re.compile(r"\bgo\s+test\b"), "go test ./..."),
)


def _makefile_test(root: Path) -> str | None:
    for name in ("Makefile", "makefile", "GNUmakefile"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"^test\s*:", text, re.MULTILINE):
            return "make test"
    just = root / "justfile"
    if just.is_file():
        try:
            text = just.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if re.search(r"^test\s*:", text, re.MULTILINE) or "test " in text:
            return "just test"
    return None


def _ci_workflow_test(root: Path) -> str | None:
    candidates: list[Path] = []
    for rel in (
        ".github/workflows",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
    ):
        path = root / rel
        if path.is_file():
            candidates.append(path)
        elif path.is_dir():
            candidates.extend(sorted(path.glob("*.yml")))
            candidates.extend(sorted(path.glob("*.yaml")))
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern, cmd in _RUN_PATTERNS:
            if pattern.search(text):
                return cmd
    return None


def canonical_test_command(root: Path) -> str | None:
    """Best-effort test command from CI workflows, then Makefile / justfile."""
    root = root.expanduser().resolve()
    return _ci_workflow_test(root) or _makefile_test(root)
