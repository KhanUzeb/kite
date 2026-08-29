"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


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
