"""Shared pytest fixtures."""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _stub_oauth_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call real Codex / Claude / Grok CLIs during pytest (CI hang)."""
    from unittest.mock import MagicMock

    from kite.providers.auth.base import AuthStatus, LoginResult

    stub = MagicMock()
    stub.status.return_value = AuthStatus(False, "not linked (test stub)", method="subscription")
    stub.fetch_model_ids.return_value = ("stub-model",)
    stub.login.return_value = LoginResult(2, "not linked (test stub)")
    stub.logout.return_value = False
    stub.litellm_env.return_value = {}
    stub.litellm_extras.return_value = {}

    monkeypatch.setattr("kite.providers.auth.get_auth_provider", lambda _key: stub)
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda _key: stub)
    # LiteLLM ChatGPT OAuth device-code login hangs pytest when resolving model capabilities.
    monkeypatch.setattr("kite.providers.capabilities._tools_from_litellm", lambda *_a, **_k: None)
