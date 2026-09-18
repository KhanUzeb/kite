"""Canonical test/verify command — single resolver for context, status, and verification."""

from __future__ import annotations

from pathlib import Path

from kite.context.ci_hints import canonical_test_command
from kite.context.project_init import detect_ecosystem


def resolve_verification_command(root: Path) -> tuple[str, str]:
    """Return ``(command, source)`` with source ``ci``, ``manifest``, or empty."""
    root = root.expanduser().resolve()
    ci = canonical_test_command(root)
    if ci:
        return ci, "ci"
    test = detect_ecosystem(root).test
    if test and test != "<test command>":
        return test, "manifest"
    return "", ""
