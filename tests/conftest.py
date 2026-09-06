"""Shared pytest fixtures."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


@pytest.fixture
def kite_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated ~/.kite for session/audit tests."""
    home = tmp_path / "kite_home"
    home.mkdir()
    monkeypatch.setenv("KITE_HOME", str(home))
    return home


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Minimal project workspace with src/ subtree."""
    root = tmp_path / "proj"
    src = root / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _stop_kite_spinners():
    """Ensure WaitSpinner daemon threads never outlive a test (CI 3.11 abort)."""
    yield
    from kite.ui.spinner import stop_all_spinners

    stop_all_spinners()
