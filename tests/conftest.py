"""Shared pytest fixtures."""

from __future__ import annotations

import ipaddress
import re
import socket
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
def _scrub_relay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relay detection is env-based: Orca-managed dev shells export ORCA_*,
    which would otherwise flip narrow rendering on for every test here.
    Scrub so the suite is hermetic; relay tests opt back in explicitly."""
    from kite.util.tty import ORCA_RELAY_MARKERS

    for var in (*ORCA_RELAY_MARKERS, "KITE_COMPACT_UI"):
        monkeypatch.delenv(var, raising=False)
    yield


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


@pytest.fixture(autouse=True)
def _block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow local test servers and Unix sockets, never external services."""
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    create_connection = socket.create_connection

    def require_loopback(address) -> None:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            raise AssertionError(f"External network access blocked in tests: {address!r}")

    def local_connect(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            require_loopback(address)
        return connect(sock, address)

    def local_connect_ex(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            require_loopback(address)
        return connect_ex(sock, address)

    def local_create_connection(address, *args, **kwargs):
        require_loopback(address)
        return create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)
    monkeypatch.setattr(socket, "create_connection", local_create_connection)
